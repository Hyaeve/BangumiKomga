package providers

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"sort"
	"strconv"
	"strings"
	"time"
)

type SeriesBook struct {
	ID      string         `json:"id"`
	Name    string         `json:"name"`
	Number  *BookRange     `json:"number,omitempty"`
	Edition string         `json:"edition,omitempty"`
	Fields  map[string]any `json:"fields,omitempty"`
	Cover   string         `json:"cover,omitempty"`
}

type BookRange struct {
	Start float64 `json:"start"`
	End   float64 `json:"end"`
}

func rangeNumber(value any) *BookRange {
	n, err := strconv.ParseFloat(text(value), 64)
	if err != nil {
		return nil
	}
	return &BookRange{Start: n, End: n}
}

func Books(ctx context.Context, config Config, name, id string) ([]SeriesBook, error) {
	entries, err := config.registry()
	if err != nil {
		return nil, err
	}
	for _, entry := range entries {
		if entry.provider.Name() == name {
			if enabled, exists := entry.options.Fields["books"]; exists && !enabled {
				return []SeriesBook{}, nil
			}
			return entry.provider.(*remoteProvider).books(ctx, id)
		}
	}
	return nil, errors.New("provider is disabled")
}

func Book(ctx context.Context, config Config, name, seriesID, id string) (SeriesBook, error) {
	entries, err := config.registry()
	if err != nil {
		return SeriesBook{}, err
	}
	for _, entry := range entries {
		if entry.provider.Name() == name {
			item, err := entry.provider.(*remoteProvider).book(ctx, seriesID, id)
			if err == nil {
				for key, value := range item.Fields {
					if enabled, exists := entry.options.BookFields[key]; exists && !enabled {
						delete(item.Fields, key)
					} else if value == nil || value == "" {
						delete(item.Fields, key)
					} else if key == "summary" {
						item.Fields[key] = plain(text(value))
					}
				}
				if enabled, exists := entry.options.BookFields["thumbnail"]; exists && !enabled {
					item.Cover = ""
				}
			}
			return item, err
		}
	}
	return SeriesBook{}, errors.New("provider is disabled")
}

func (p *remoteProvider) books(ctx context.Context, id string) ([]SeriesBook, error) {
	result := []SeriesBook{}
	switch p.Name() {
	case "MANGADEX":
		var covers []any
		for offset := 0; ; {
			data, err := p.json(ctx, "GET", queryURL("https://api.mangadex.org/cover", url.Values{
				"manga[]": {id}, "limit": {"100"}, "offset": {strconv.Itoa(offset)},
			}), nil, nil)
			if err != nil {
				return nil, err
			}
			rows := array(data["data"])
			covers = append(covers, rows...)
			offset += len(rows)
			if len(rows) == 0 || offset >= number(data["total"]) {
				break
			}
		}
		languages := p.option.CoverLanguages
		if languages == nil {
			languages = []string{"en", "ja"}
		}
		seen := map[string]bool{}
		for _, language := range languages {
			for _, cover := range covers {
				attr := obj(obj(cover)["attributes"])
				volume := text(attr["volume"])
				if text(attr["locale"]) != language || seen[volume] {
					continue
				}
				seen[volume] = true
				result = append(result, SeriesBook{ID: text(attr["fileName"]), Name: volume, Number: rangeNumber(attr["volume"])})
			}
		}
	case "COMIC_VINE":
		item, err := p.Get(ctx, id)
		if err != nil {
			return nil, err
		}
		for _, row := range array(item.Raw["issues"]) {
			issue := obj(row)
			result = append(result, SeriesBook{ID: text(issue["id"]), Name: text(issue["name"]), Number: rangeNumber(issue["issue_number"])})
		}
	case "BOOK_WALKER":
		db, err := p.openDatabase()
		if err != nil {
			return nil, err
		}
		defer db.Close()
		rows, err := readRows(ctx, db, "SELECT id,display_title,display_order FROM products WHERE series_id=?", id)
		if err != nil {
			return nil, err
		}
		for _, row := range rows {
			result = append(result, SeriesBook{ID: text(row["id"]), Name: text(row["display_title"]), Number: rangeNumber(row["display_order"])})
		}
	case "WEBTOONS":
		rows, err := p.episodes(ctx, id)
		if err != nil {
			return nil, err
		}
		for index, row := range rows {
			item := webtoonBook(row, index)
			item.Fields, item.Cover = nil, ""
			result = append(result, item)
		}
	case "YEN_PRESS":
		next, seen := "99999", map[string]bool{}
		for page := 0; page <= 50 && next != "" && !seen[next]; page++ {
			seen[next] = true
			doc, err := p.document(ctx, queryURL("https://yenpress.com/series/get_more/"+url.PathEscape(id), url.Values{"next_ord": {next}}),
				map[string]string{"X-Requested-With": "XMLHttpRequest"})
			if err != nil {
				return nil, err
			}
			links := doc.Find(".inline_block a[href^='/titles/']")
			for index := 0; index < links.Length(); index++ {
				link := links.Eq(index)
				path, _ := link.Attr("href")
				name := selectionText(link.Children().Eq(1))
				if name == "" {
					name = selectionText(link)
				}
				result = append(result, SeriesBook{ID: strings.TrimPrefix(path, "/titles/"), Name: name, Number: parseBookRange(name, "comic")})
			}
			address, _ := doc.Find(".show-more").Attr("data-url")
			u, _ := url.Parse(address)
			next = ""
			if u != nil {
				next = u.Query().Get("next_ord")
			}
		}
		sort.SliceStable(result, func(i, j int) bool {
			return result[i].Number != nil && (result[j].Number == nil || result[i].Number.Start < result[j].Number.Start)
		})
	case "VIZ":
		doc, err := p.vizDocument(ctx, id)
		if err != nil {
			return nil, err
		}
		heading := doc.Find("#purchase_links_block h2").First()
		all, _ := heading.Find("a[href$='/all']").Attr("href")
		if all == "" {
			all, _ = heading.PrevFiltered("a[href$='/all']").Attr("href")
		}
		if !strings.HasPrefix(all, "/manga-books/manga/") {
			name := selectionText(heading)
			return []SeriesBook{{ID: id, Name: name, Number: parseBookRange(name, "comic")}}, nil
		}
		list, err := p.document(ctx, "https://www.viz.com"+all, nil)
		if err != nil {
			return nil, err
		}
		links, seen := list.Find("#c-0-s-0 a[href^='/manga-books/manga/']"), map[string]bool{}
		for index := 0; index < links.Length(); index++ {
			link := links.Eq(index)
			path, _ := link.Attr("href")
			name := selectionText(link)
			if name == "" || seen[path] || strings.HasSuffix(path, "/all") {
				continue
			}
			seen[path] = true
			result = append(result, SeriesBook{ID: strings.TrimPrefix(path, "/manga-books/manga/"), Name: name, Number: parseBookRange(name, "comic")})
		}
	}
	return result, nil
}

func (p *remoteProvider) book(ctx context.Context, seriesID, id string) (SeriesBook, error) {
	item := SeriesBook{ID: id, Fields: map[string]any{}}
	switch p.Name() {
	case "MANGADEX":
		item.Cover = "https://uploads.mangadex.org/covers/" + url.PathEscape(seriesID) + "/" + url.PathEscape(id)
	case "COMIC_VINE":
		data, err := p.json(ctx, "GET", queryURL("https://comicvine.gamespot.com/api/issue/4000-"+url.PathEscape(id)+"/",
			url.Values{"api_key": {p.option.APIKey}, "format": {"json"}}), nil, nil)
		if err != nil {
			return item, err
		}
		row := obj(data["results"])
		if number(data["status_code"]) != 1 || text(row["id"]) != id || text(child(row, "volume", "id")) != seriesID {
			return item, errors.New("ComicVine issue does not belong to matched series")
		}
		item.Name, item.Number = text(row["name"]), rangeNumber(row["issue_number"])
		item.Fields["title"], item.Fields["summary"] = row["name"], row["description"]
		item.Fields["releaseDate"] = first(text(row["store_date"]), text(row["cover_date"]))
		if item.Number != nil {
			item.Fields["number"], item.Fields["numberSort"] = text(row["issue_number"]), item.Number.Start
		}
		item.Fields["links"] = []map[string]string{{"label": "ComicVine", "url": text(row["site_detail_url"])}}
		item.Cover = comicVineCover(row)
	case "BOOK_WALKER":
		db, err := p.openDatabase()
		if err != nil {
			return item, err
		}
		defer db.Close()
		rows, err := readRows(ctx, db, `SELECT p.*,e.external_id AS isbn FROM products p
			LEFT JOIN product_external_ids e ON p.id=e.product_id AND e.type=3 WHERE p.id=? AND p.series_id=?`, id, seriesID)
		if err != nil {
			return item, err
		}
		if len(rows) != 1 {
			return item, errors.New("BookWalker book does not belong to matched series")
		}
		row := rows[0]
		item.Name, item.Number = text(row["title"]), rangeNumber(row["display_order"])
		item.Fields["title"], item.Fields["summary"], item.Fields["isbn"] = row["title"], row["description"], row["isbn"]
		if date := text(row["on_sale_at"]); len(date) >= 10 {
			item.Fields["releaseDate"] = date[:10]
		}
		if item.Number != nil {
			item.Fields["number"] = strconv.FormatFloat(item.Number.Start, 'f', -1, 64)
		}
		item.Fields["links"] = []map[string]string{{"label": "BookWalker", "url": "https://bookwalker.com/" + url.PathEscape(id)}}
	case "WEBTOONS":
		rows, err := p.episodes(ctx, seriesID)
		if err != nil {
			return item, err
		}
		for index, row := range rows {
			book := webtoonBook(row, index)
			if book.ID == id {
				return book, nil
			}
		}
		return item, errors.New("Webtoons episode not in series")
	case "YEN_PRESS":
		doc, err := p.document(ctx, "https://yenpress.com/titles/"+url.PathEscape(id), nil)
		if err != nil {
			return item, err
		}
		item.Name = selectionText(doc.Find(".heading-content .heading").First())
		item.Number = parseBookRange(item.Name, "comic")
		item.Fields["title"] = strings.TrimSpace(yenKind.ReplaceAllString(item.Name, ""))
		item.Fields["summary"] = selectionText(doc.Find(".book-info .content-heading-txt").First().Children().Eq(1))
		item.Cover, _ = doc.Find(".book-info .series-cover img").Attr("data-src")
		details := doc.Find(".book-details .detail-info div")
		for index := 0; index < details.Length(); index++ {
			row := details.Eq(index)
			if row.Find("div").Length() != 0 {
				continue
			}
			key, value := selectionText(row.Children().First()), selectionText(row.Children().Eq(1))
			switch key {
			case "ISBN":
				item.Fields["isbn"] = value
			case "Release Date":
				for _, layout := range []string{"Jan 2, 2006", "January 2, 2006"} {
					if date, err := time.Parse(layout, value); err == nil {
						item.Fields["releaseDate"] = date.Format("2006-01-02")
						break
					}
				}
			}
		}
		if item.Number != nil {
			item.Fields["number"], item.Fields["numberSort"] = strconv.FormatFloat(item.Number.Start, 'f', -1, 64), item.Number.Start
		}
		item.Fields["links"] = []map[string]string{{"label": "YenPress", "url": "https://yenpress.com/titles/" + url.PathEscape(id)}}
	case "VIZ":
		doc, err := p.vizDocument(ctx, id)
		if err != nil {
			return item, err
		}
		product := doc.Find("#product_row")
		item.Name = selectionText(product.Find("#purchase_links_block h2").First())
		item.Number = parseBookRange(item.Name, "comic")
		item.Fields["title"] = item.Name
		item.Fields["summary"] = selectionText(product.Children().Eq(1).Children().Eq(1))
		item.Cover, _ = product.Find("#product_image_block img").Attr("src")
		if item.Number != nil {
			item.Fields["number"], item.Fields["numberSort"] = strconv.FormatFloat(item.Number.Start, 'f', -1, 64), item.Number.Start
		}
		item.Fields["links"] = []map[string]string{{"label": "Viz", "url": "https://www.viz.com/manga-books/manga/" + id}}
	default:
		return item, errors.New("provider has no associated book metadata")
	}
	return item, nil
}

func (p *remoteProvider) episodes(ctx context.Context, id string) ([]object, error) {
	u, err := url.Parse(id)
	if err != nil || u.Query().Get("title_no") == "" {
		return nil, errors.New("invalid Webtoons series")
	}
	kind := "webtoon"
	if strings.Contains(id, "/canvas/") {
		kind = "canvas"
	}
	data, err := p.json(ctx, "GET", "https://m.webtoons.com/api/v1/"+kind+"/"+url.PathEscape(u.Query().Get("title_no"))+"/episodes?pageSize=99999",
		nil, map[string]string{"Referer": "https://m.webtoons.com/"})
	if err != nil {
		return nil, err
	}
	rows := []object{}
	for _, value := range array(child(data, "result", "episodeList")) {
		rows = append(rows, obj(value))
	}
	return rows, nil
}

func webtoonBook(row object, index int) SeriesBook {
	item := SeriesBook{ID: text(row["viewerLink"]), Name: text(row["episodeTitle"]), Number: &BookRange{float64(index + 1), float64(index + 1)},
		Fields: map[string]any{"title": row["episodeTitle"], "number": fmt.Sprint(index + 1)}}
	if millis := decimal(row["exposureDateMillis"]); millis > 0 {
		item.Fields["releaseDate"] = time.UnixMilli(int64(millis)).UTC().Format("2006-01-02")
	}
	item.Fields["links"] = []map[string]string{{"label": "Webtoon", "url": "https://www.webtoons.com" + item.ID}}
	item.Cover = "https://webtoon-phinf.pstatic.net" + text(row["thumbnail"])
	return item
}
