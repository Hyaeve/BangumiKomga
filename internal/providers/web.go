package providers

import (
	"context"
	"errors"
	"net/url"
	"regexp"
	"strconv"
	"strings"

	"github.com/PuerkitoBio/goquery"
)

var volumeSuffix = regexp.MustCompile(`(?i),?\s+Vol\.?\s*[0-9]+.*$`)
var galleryLink = regexp.MustCompile(`https://e-hentai\.org/g/([0-9]+)/([a-f0-9]+)/?`)

func (p *remoteProvider) document(ctx context.Context, address string, headers map[string]string) (*goquery.Document, error) {
	data, err := p.request(ctx, "GET", address, nil, headers)
	if err != nil {
		return nil, err
	}
	return goquery.NewDocumentFromReader(strings.NewReader(string(data)))
}

func (p *remoteProvider) webSearch(ctx context.Context, query, media string) ([]Metadata, error) {
	result := []Metadata{}
	switch p.Name() {
	case "YEN_PRESS":
		key := "search-vhfh3tijxttuxhjjmzgajcd4"
		body := object{"query": query, "filters": object{"all": []any{object{"all": []any{object{"type": "series"}}}}},
			"precision": 2, "search_fields": object{"title": object{"weight": 10}},
			"result_fields": object{"title": object{"raw": object{}}, "url": object{"raw": object{}}, "image": object{"raw": object{}}},
			"page":          object{"size": 10, "current": 1}}
		data, err := p.json(ctx, "POST", "https://enterprise-search.yenpress.com/api/as/v1/engines/yenpress/search.json",
			body, map[string]string{"Authorization": "Bearer " + key})
		if err != nil && err.Error() == "HTTP 401" {
			doc, keyErr := p.document(ctx, "https://yenpress.com/search", nil)
			if keyErr != nil {
				return nil, keyErr
			}
			keyPattern := regexp.MustCompile(`"search_key"\s*:\s*"([^"]+)"`)
			match := keyPattern.FindStringSubmatch(doc.Find("script").Text())
			if len(match) != 2 {
				return nil, errors.New("YenPress search key not found")
			}
			data, err = p.json(ctx, "POST", "https://enterprise-search.yenpress.com/api/as/v1/engines/yenpress/search.json",
				body, map[string]string{"Authorization": "Bearer " + match[1]})
		}
		if err != nil {
			return nil, err
		}
		for _, row := range array(data["results"]) {
			r := obj(row)
			path := text(child(r, "url", "raw"))
			if !strings.HasPrefix(path, "/series/") {
				continue
			}
			name := text(child(r, "title", "raw"))
			if strings.Contains(name, "(audio)") {
				continue
			}
			kind := "comic"
			if strings.Contains(strings.ToLower(name), "novel") {
				kind = "book"
			}
			item := newMetadata(p.Name(), strings.TrimPrefix(path, "/series/"), kind)
			title(&item, name, "en")
			result = append(result, item)
		}
	case "VIZ":
		if media == "book" {
			return result, nil
		}
		doc, err := p.document(ctx, queryURL("https://www.viz.com/search",
			url.Values{"search": {query + ", Vol. 1"}, "category": {"Manga"}}), nil)
		if err != nil {
			return nil, err
		}
		seen := map[string]bool{}
		doc.Find("#results a[href]").Each(func(_ int, link *goquery.Selection) {
			path, _ := link.Attr("href")
			name := selectionText(link)
			if !strings.HasPrefix(path, "/manga-books/manga/") || !regexp.MustCompile(`(?i)Vol\.\s*1(?:\D|$)`).MatchString(name) || seen[path] {
				return
			}
			seen[path] = true
			item := newMetadata(p.Name(), strings.TrimPrefix(path, "/manga-books/manga/"), "comic")
			title(&item, volumeSuffix.ReplaceAllString(name, ""), "en")
			result = append(result, item)
		})
	case "WEBTOONS":
		if media == "book" {
			return result, nil
		}
		for _, kind := range []string{"WEBTOON", "CHALLENGE"} {
			data, err := p.json(ctx, "GET", queryURL("https://m.webtoons.com/undefined/search/result",
				url.Values{"keyword": {query}, "searchType": {kind}}), nil,
				map[string]string{"Referer": "https://m.webtoons.com/", "Accept": "application/json"})
			if err != nil {
				return nil, err
			}
			group := "webtoonResult"
			if kind == "CHALLENGE" {
				group = "challengeResult"
			}
			for _, row := range array(child(data, "result", group, "titleList")) {
				value := obj(row)
				slug := text(value["titleGroupName"])
				if slug == "" {
					slug = strings.ReplaceAll(strings.ToLower(text(value["title"])), " ", "-")
				}
				genre := text(value["representGenre"])
				if kind == "CHALLENGE" {
					genre = "canvas"
				}
				if genre == "" || text(value["titleNo"]) == "" {
					continue
				}
				id := "/en/" + url.PathEscape(genre) + "/" + url.PathEscape(slug) + "/list?title_no=" + text(value["titleNo"])
				item := newMetadata(p.Name(), id, "comic")
				title(&item, text(value["title"]), "en")
				result = append(result, item)
			}
		}
	case "EHENTAI":
		if media == "book" {
			return result, nil
		}
		doc, err := p.document(ctx, queryURL("https://e-hentai.org/", url.Values{"f_search": {query}}), nil)
		if err != nil {
			return nil, err
		}
		ids, seen := []string{}, map[string]bool{}
		doc.Find("a[href]").Each(func(_ int, link *goquery.Selection) {
			href, _ := link.Attr("href")
			match := galleryLink.FindStringSubmatch(href)
			if len(match) == 3 {
				id := match[1] + ";" + match[2]
				if !seen[id] && len(ids) < 25 {
					seen[id] = true
					ids = append(ids, id)
				}
			}
		})
		for _, id := range ids {
			item, err := p.gallery(ctx, id)
			if err != nil {
				return nil, err
			}
			result = append(result, item)
		}
	}
	return result, nil
}

func selectionText(selection *goquery.Selection) string {
	return strings.Join(strings.Fields(selection.Text()), " ")
}

func (p *remoteProvider) webGet(ctx context.Context, id string) (Metadata, error) {
	if strings.Contains(id, "..") || strings.ContainsAny(id, "\\\r\n") {
		return Metadata{}, errors.New("invalid provider path")
	}
	if p.Name() == "EHENTAI" {
		return p.gallery(ctx, id)
	}
	item := newMetadata(p.Name(), id, "comic")
	switch p.Name() {
	case "WEBTOONS":
		if !strings.HasPrefix(id, "/en/") || !strings.Contains(id, "/list?title_no=") {
			return Metadata{}, errors.New("invalid Webtoons series id")
		}
		doc, err := p.document(ctx, "https://www.webtoons.com"+id, nil)
		if err != nil {
			return Metadata{}, err
		}
		title(&item, selectionText(doc.Find("h1.subj,h3.subj").First()), "en")
		item.Fields["summary"] = selectionText(doc.Find("#_asideDetail p.summary"))
		genres := []string{}
		doc.Find(".detail_header > div.info .genre").Each(func(_ int, s *goquery.Selection) { genres = append(genres, selectionText(s)) })
		item.Fields["genres"] = genres
		status := selectionText(doc.Find("#_asideDetail p.day_info"))
		if strings.Contains(status, "COMPLETED") || strings.Contains(status, "END") {
			setStatus(&item, "completed")
		} else if strings.Contains(status, "EVERY") || strings.Contains(status, "UP") {
			setStatus(&item, "ongoing")
		}
		item.Cover, _ = doc.Find(`meta[property="og:image"]`).Attr("content")
		source(&item, "Webtoons", "https://www.webtoons.com"+id)
	case "VIZ":
		doc, err := p.vizDocument(ctx, id)
		if err != nil {
			return Metadata{}, err
		}
		product := doc.Find("#product_row")
		title(&item, volumeSuffix.ReplaceAllString(selectionText(product.Find("#purchase_links_block h2").First()), ""), "en")
		item.Fields["summary"] = selectionText(product.Children().Eq(1).Children().Eq(1))
		item.Fields["publisher"] = "Viz"
		item.Cover, _ = product.Find("#product_image_block img").Attr("src")
		source(&item, "Viz", "https://www.viz.com/manga-books/manga/"+id)
	case "YEN_PRESS":
		// Series metadata comes from the first numbered volume, not a generic
		// series-page OpenGraph description.
		books, err := p.books(ctx, id)
		if err != nil {
			return Metadata{}, err
		}
		var selected *SeriesBook
		for index := range books {
			if books[index].Number != nil || len(books) == 1 {
				selected = &books[index]
				break
			}
		}
		if selected == nil {
			return Metadata{}, errors.New("YenPress volume list not found")
		}
		book, err := p.document(ctx, "https://yenpress.com/titles/"+url.PathEscape(selected.ID), nil)
		if err != nil {
			return Metadata{}, err
		}
		name := selectionText(book.Find(".heading-content .heading").First())
		if strings.Contains(strings.ToLower(name), "novel") {
			item.Media = "book"
		}
		title(&item, yenTitle(name), "en")
		item.Fields["summary"] = selectionText(book.Find(".book-info .content-heading-txt").First().Children().Eq(1))
		item.Cover, _ = book.Find(".book-info .series-cover img").Attr("data-src")
		book.Find(".book-details .detail-info div").Each(func(_ int, row *goquery.Selection) {
			if row.Find("div").Length() == 0 && row.Children().Length() >= 2 &&
				selectionText(row.Children().First()) == "Imprint" {
				item.Fields["publisher"] = selectionText(row.Children().Eq(1))
			}
		})
		source(&item, "YenPress", "https://yenpress.com/series/"+url.PathEscape(id))
	}
	if len(item.Titles) == 0 {
		return Metadata{}, errors.New("provider page did not contain expected metadata")
	}
	return item, nil
}

func (p *remoteProvider) vizDocument(ctx context.Context, id string) (*goquery.Document, error) {
	if strings.Contains(id, "..") || strings.ContainsAny(id, "\\\r\n?#") {
		return nil, errors.New("invalid Viz book id")
	}
	path := "https://www.viz.com/manga-books/manga/" + strings.TrimSuffix(id, "/all")
	doc, err := p.document(ctx, path+"/digital", nil)
	if err != nil && err.Error() == "HTTP 404" {
		return p.document(ctx, path+"/product", nil)
	}
	return doc, err
}

func (p *remoteProvider) gallery(ctx context.Context, id string) (Metadata, error) {
	parts := strings.Split(id, ";")
	if len(parts) != 2 || !regexp.MustCompile(`^[a-f0-9]+$`).MatchString(parts[1]) {
		return Metadata{}, errors.New("invalid gallery id")
	}
	gid, err := strconv.ParseInt(parts[0], 10, 64)
	if err != nil || gid <= 0 {
		return Metadata{}, errors.New("invalid gallery id")
	}
	data, err := p.json(ctx, "POST", "https://api.e-hentai.org/api.php",
		object{"method": "gdata", "gidlist": []any{[]any{gid, parts[1]}}, "namespace": 1}, nil)
	if err != nil {
		return Metadata{}, err
	}
	rows := array(data["gmetadata"])
	if len(rows) != 1 || obj(rows[0])["error"] != nil {
		return Metadata{}, errors.New("gallery metadata not available")
	}
	row := obj(rows[0])
	if text(row["gid"]) != parts[0] {
		return Metadata{}, errors.New("gallery id mismatch")
	}
	item := newMetadata(p.Name(), id, "comic")
	item.Raw = row
	clean := func(value string) string {
		value = regexp.MustCompile(`^(?:\([^)]+\)\s*)?(?:\[[^]]+\]\s*)?`).ReplaceAllString(value, "")
		value = regexp.MustCompile(`(?:\s*\[[^]]+\])+$`).ReplaceAllString(value, "")
		values := strings.Split(value, "|")
		return strings.TrimSpace(values[len(values)-1])
	}
	title(&item, clean(text(row["title_jpn"])), "ja")
	title(&item, clean(text(row["title"])), "en")
	item.Cover = text(row["thumb"])
	item.Fields["status"] = "ENDED"
	item.Fields["ageRating"] = 18
	tags := filterEHTags(stringsIn(row["tags"]))
	for _, tag := range stringsIn(row["tags"]) {
		namespace, value, ok := strings.Cut(tag, ":")
		if !ok {
			continue
		}
		switch namespace {
		case "language":
			for name, code := range map[string]string{"chinese": "zh", "japanese": "ja", "english": "en", "korean": "ko"} {
				if value == name {
					item.Fields["language"] = code
				}
			}
		}
	}
	item.Fields["tags"] = tags
	source(&item, "e-hentai", "https://e-hentai.org/g/"+parts[0]+"/"+parts[1]+"/")
	return item, nil
}
