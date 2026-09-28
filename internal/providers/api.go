package providers

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"regexp"
	"sort"
	"strings"
)

const aniFields = `id format title { english romaji native } description(asHtml:false)
status volumes genres tags { name rank } siteUrl coverImage { extraLarge large }
staff { edges { role node { name { full userPreferred } } } }`

const malFields = "id,title,main_picture,alternative_titles,start_date,end_date,synopsis,mean,rank,media_type,status,num_volumes,num_chapters,genres,authors{first_name,last_name},pictures"

func (p *remoteProvider) Search(ctx context.Context, query, media string) ([]Metadata, error) {
	var rows []any
	var err error
	switch p.Name() {
	case "MANGA_UPDATES":
		types := []string{"Manga", "Manhwa", "Manhua", "Artbook", "Doujinshi", "Filipino",
			"Indonesian", "Thai", "Vietnamese", "Malaysian", "OEL", "Nordic", "French", "Spanish"}
		if media == "book" {
			types = []string{"Novel"}
		} else if media == "mixed" {
			types = append(types, "Novel")
		}
		var data object
		data, err = p.json(ctx, "POST", "https://api.mangaupdates.com/v1/series/search",
			object{"search": query, "page": 1, "perpage": 5, "type": types}, nil)
		for _, value := range array(data["results"]) {
			rows = append(rows, obj(value)["record"])
		}
	case "ANILIST":
		formats := []string{"MANGA", "ONE_SHOT"}
		if media == "book" {
			formats = []string{"NOVEL"}
		} else if media == "mixed" {
			formats = append(formats, "NOVEL")
		}
		var data object
		data, err = p.json(ctx, "POST", "https://graphql.anilist.co", object{
			"query":     `query($search:String,$formats:[MediaFormat!]!){mediaSearch:Page(page:1,perPage:10){media(search:$search,type:MANGA,format_in:$formats){` + aniFields + `}}}`,
			"variables": object{"search": query, "formats": formats},
		}, p.authHeaders())
		rows = array(child(data, "data", "mediaSearch", "media"))
	case "MAL":
		if len([]rune(query)) < 3 {
			return []Metadata{}, nil
		}
		query = truncate(query, 64)
		if p.option.APIKey == "" && p.option.Token == "" {
			return nil, errors.New("requires MAL client ID or access token")
		}
		var data object
		data, err = p.json(ctx, "GET", queryURL("https://api.myanimelist.net/v2/manga", url.Values{
			"q": {query}, "fields": {"alternative_titles,media_type"}, "nsfw": {"true"},
		}), nil, p.authHeaders())
		for _, value := range array(data["data"]) {
			rows = append(rows, obj(value)["node"])
		}
	case "MANGADEX":
		if media == "book" {
			return []Metadata{}, nil
		}
		var data object
		params := dexParams()
		params.Set("title", query)
		params.Set("limit", "5")
		params.Set("order[relevance]", "desc")
		params["contentRating[]"] = []string{"safe", "suggestive", "erotica", "pornographic"}
		data, err = p.json(ctx, "GET", queryURL("https://api.mangadex.org/manga", params), nil, nil)
		if err == nil && text(data["result"]) != "ok" {
			return nil, errors.New("MangaDex rejected search")
		}
		rows = array(data["data"])
	case "COMIC_VINE":
		if media == "book" {
			return []Metadata{}, nil
		}
		if p.option.APIKey == "" {
			return nil, errors.New("requires ComicVine API key")
		}
		var data object
		data, err = p.json(ctx, "GET", queryURL("https://comicvine.gamespot.com/api/search/", url.Values{
			"api_key": {p.option.APIKey}, "format": {"json"}, "query": {query}, "resources": {"volume"}, "limit": {"20"},
		}), nil, nil)
		if err == nil && number(data["status_code"]) != 1 {
			return nil, errors.New("ComicVine API rejected search")
		}
		rows = array(data["results"])
	case "MANGA_BAKA":
		if p.option.Database != "" {
			return p.databaseSearch(ctx, query, media)
		}
		params := url.Values{"q": {query}}
		if media == "book" {
			params["type"] = []string{"novel"}
		} else if media == "comic" {
			params["type_not"] = []string{"novel"}
		}
		var data object
		data, err = p.json(ctx, "GET", queryURL("https://api.mangabaka.org/v1/series/search", params), nil, nil)
		rows = array(data["data"])
	case "BOOK_WALKER":
		return p.databaseSearch(ctx, query, media)
	case "YEN_PRESS", "VIZ", "WEBTOONS", "EHENTAI":
		return p.webSearch(ctx, query, media)
	default:
		return nil, errors.New("unregistered provider")
	}
	if err != nil {
		return nil, err
	}
	result := []Metadata{}
	for _, row := range rows {
		item := p.mapAPI(obj(row))
		// MangaUpdates search records omit type. The request already carries
		// its type filter; the detail response is checked again before use.
		if p.Name() == "MANGA_UPDATES" && item.Media == "" {
			item.Media = "comic"
			if media == "book" || strings.HasSuffix(text(obj(row)["title"]), " (Novel)") {
				item.Media = "book"
			}
		}
		if item.ID != "" && mediaAllowed(media, item.Media) && len(item.Titles) > 0 {
			result = append(result, item)
		}
		if len(result) >= 100 {
			break
		}
	}
	return result, nil
}

func (p *remoteProvider) Get(ctx context.Context, id string) (Metadata, error) {
	if id == "" || len(id) > 1000 {
		return Metadata{}, errors.New("invalid provider id")
	}
	var data object
	var err error
	escaped := url.PathEscape(id)
	switch p.Name() {
	case "MANGA_UPDATES":
		data, err = p.json(ctx, "GET", "https://api.mangaupdates.com/v1/series/"+escaped, nil, nil)
	case "ANILIST":
		var numericID int
		if _, err = fmt.Sscan(id, &numericID); err != nil || numericID <= 0 {
			return Metadata{}, errors.New("invalid AniList id")
		}
		data, err = p.json(ctx, "POST", "https://graphql.anilist.co", object{
			"query":     `query($id:Int){Media(id:$id,type:MANGA){` + aniFields + `}}`,
			"variables": object{"id": numericID},
		}, p.authHeaders())
		data = obj(child(data, "data", "Media"))
	case "MAL":
		if p.option.APIKey == "" && p.option.Token == "" {
			return Metadata{}, errors.New("requires MAL client ID or access token")
		}
		data, err = p.json(ctx, "GET", queryURL("https://api.myanimelist.net/v2/manga/"+escaped,
			url.Values{"fields": {malFields}}), nil, p.authHeaders())
	case "MANGADEX":
		data, err = p.json(ctx, "GET", queryURL("https://api.mangadex.org/manga/"+escaped, dexParams()), nil, nil)
		if err == nil && text(data["result"]) != "ok" {
			return Metadata{}, errors.New("MangaDex rejected detail lookup")
		}
		data = obj(data["data"])
	case "COMIC_VINE":
		if p.option.APIKey == "" {
			return Metadata{}, errors.New("requires ComicVine API key")
		}
		data, err = p.json(ctx, "GET", queryURL("https://comicvine.gamespot.com/api/volume/4050-"+escaped+"/",
			url.Values{"api_key": {p.option.APIKey}, "format": {"json"}}), nil, nil)
		if err == nil && number(data["status_code"]) != 1 {
			return Metadata{}, errors.New("ComicVine API rejected detail lookup")
		}
		data = obj(data["results"])
	case "MANGA_BAKA":
		if p.option.Database != "" {
			return p.databaseGet(ctx, id)
		}
		data, err = p.json(ctx, "GET", "https://api.mangabaka.org/v1/series/"+escaped, nil, nil)
		data = obj(data["data"])
	case "BOOK_WALKER":
		return p.databaseGet(ctx, id)
	case "YEN_PRESS", "VIZ", "WEBTOONS", "EHENTAI":
		return p.webGet(ctx, id)
	default:
		return Metadata{}, errors.New("unregistered provider")
	}
	if err != nil {
		return Metadata{}, err
	}
	item := p.mapAPI(data)
	if item.ID != id || len(item.Titles) == 0 {
		return Metadata{}, errors.New("provider detail is missing or belongs to another id")
	}
	return item, nil
}

func dexParams() url.Values {
	return url.Values{"includes[]": {"cover_art", "author", "artist"}}
}

func (p *remoteProvider) authHeaders() map[string]string {
	headers := map[string]string{}
	if p.Name() == "MAL" && p.option.APIKey != "" {
		headers["X-MAL-CLIENT-ID"] = p.option.APIKey
	}
	if p.option.Token != "" {
		headers["Authorization"] = "Bearer " + p.option.Token
	}
	return headers
}

func (p *remoteProvider) mapAPI(data object) Metadata {
	item := newMetadata(p.Name(), text(data["id"]), "")
	item.Raw = data
	item.Fields["authors"] = p.authors(data)
	switch p.Name() {
	case "MANGA_UPDATES":
		item.ID, item.Media = text(data["series_id"]), mediaKind(text(data["type"]))
		title(&item, strings.TrimSuffix(text(data["title"]), " (Novel)"), "ja-ro")
		for _, value := range array(data["associated"]) {
			title(&item, text(obj(value)["title"]), "")
		}
		item.Fields["summary"] = data["description"]
		item.Fields["genres"] = addNames(array(data["genres"]), "genre")
		categories := array(data["categories"])
		sort.SliceStable(categories, func(i, j int) bool { return number(obj(categories[i])["votes"]) > number(obj(categories[j])["votes"]) })
		item.Fields["tags"] = addNames(categories[:min(15, len(categories))], "category")
		item.Fields["publisher"] = publisher(array(data["publishers"]), "publisher_name", p.option.UseOriginalPublisher)
		groups := regexp.MustCompile(`\(([^)]+)\)`).FindAllStringSubmatch(text(data["status"]), -1)
		if len(groups) > 0 {
			consistent := true
			for _, group := range groups {
				if !strings.Contains(group[1], groups[0][1]) {
					consistent = false
				}
			}
			if consistent {
				setStatus(&item, groups[0][1])
			}
		}
		item.Cover = text(child(data, "image", "url", "original"))
		source(&item, "MangaUpdates", first(text(data["url"]), "https://www.mangaupdates.com/series/"+item.ID))
	case "ANILIST":
		item.Media = mediaKind(text(data["format"]))
		for _, pair := range [][2]string{{"english", "en"}, {"romaji", "ja-ro"}, {"native", "ja"}} {
			title(&item, text(child(data, "title", pair[0])), pair[1])
		}
		item.Fields["summary"], item.Fields["genres"] = data["description"], stringsIn(data["genres"])
		setStatus(&item, text(data["status"]))
		positive(&item, "totalBookCount", data["volumes"])
		threshold, limit := 60, 15
		if p.option.TagsScoreThreshold != nil {
			threshold = *p.option.TagsScoreThreshold
		}
		if p.option.TagsSizeLimit != nil {
			limit = max(0, min(100, *p.option.TagsSizeLimit))
		}
		tags := array(data["tags"])
		sort.SliceStable(tags, func(i, j int) bool { return number(obj(tags[i])["rank"]) > number(obj(tags[j])["rank"]) })
		names := []string{}
		for _, tag := range tags {
			if number(obj(tag)["rank"]) >= threshold && len(names) < limit {
				names = append(names, text(obj(tag)["name"]))
			}
		}
		item.Fields["tags"] = names
		item.Cover = first(text(child(data, "coverImage", "extraLarge")), text(child(data, "coverImage", "large")))
		source(&item, "AniList", "https://anilist.co/manga/"+item.ID)
	case "MAL":
		item.Media = mediaKind(text(data["media_type"]))
		title(&item, text(data["title"]), "ja-ro")
		title(&item, text(child(data, "alternative_titles", "en")), "en")
		title(&item, text(child(data, "alternative_titles", "ja")), "ja")
		for _, name := range stringsIn(child(data, "alternative_titles", "synonyms")) {
			title(&item, name, "")
		}
		item.Fields["summary"], item.Fields["genres"] = data["synopsis"], addNames(array(data["genres"]), "name")
		setStatus(&item, text(data["status"]))
		positive(&item, "totalBookCount", data["num_volumes"])
		item.Cover = first(text(child(data, "main_picture", "large")), text(child(data, "main_picture", "medium")))
		source(&item, "MyAnimeList", "https://myanimelist.net/manga/"+item.ID)
	case "MANGADEX":
		item.Media = "comic"
		attr := obj(data["attributes"])
		localizedTitles(&item, obj(attr["title"]))
		for _, alt := range array(attr["altTitles"]) {
			localizedTitles(&item, obj(alt))
		}
		description := obj(attr["description"])
		item.Fields["summary"] = localized(description, p.option.TitleLanguage)
		setStatus(&item, text(attr["status"]))
		genres, tags := []string{}, []string{}
		if demographic := strings.ToLower(text(attr["publicationDemographic"])); demographic != "" {
			genres = append(genres, demographic)
		}
		for _, tag := range array(attr["tags"]) {
			a := obj(obj(tag)["attributes"])
			name := localized(obj(a["name"]), "en")
			if text(a["group"]) == "genre" {
				genres = append(genres, name)
			} else if text(a["group"]) == "theme" {
				tags = append(tags, name)
			}
		}
		item.Fields["genres"], item.Fields["tags"] = genres, tags
		for _, relation := range array(data["relationships"]) {
			r := obj(relation)
			if text(r["type"]) == "cover_art" && text(child(r, "attributes", "fileName")) != "" {
				item.Cover = "https://uploads.mangadex.org/covers/" + item.ID + "/" + url.PathEscape(text(child(r, "attributes", "fileName")))
				break
			}
		}
		source(&item, "MangaDex", "https://mangadex.org/title/"+item.ID)
	case "COMIC_VINE":
		item.Media = "comic"
		title(&item, text(data["name"]), "en")
		for _, alias := range strings.Split(text(data["aliases"]), "\n") {
			title(&item, alias, "en")
		}
		item.Fields["summary"] = first(text(data["description"]), text(data["deck"]))
		item.Fields["publisher"] = text(child(data, "publisher", "name"))
		positive(&item, "totalBookCount", data["count_of_issues"])
		item.Cover = comicVineCover(data)
		source(&item, "ComicVine", first(text(data["site_detail_url"]), "https://comicvine.gamespot.com/volume/4050-"+item.ID+"/"))
	case "MANGA_BAKA":
		item.Media = mediaKind(text(data["type"]))
		titles := array(data["titles"])
		sort.SliceStable(titles, func(i, j int) bool {
			return obj(titles[i])["is_primary"] == true && obj(titles[j])["is_primary"] != true
		})
		for _, value := range titles {
			title(&item, text(obj(value)["title"]), strings.ReplaceAll(text(obj(value)["language"]), "-Latn", "-ro"))
		}
		if len(item.Titles) == 0 {
			title(&item, text(data["title"]), "")
		}
		item.Fields["summary"] = data["description"]
		item.Fields["publisher"] = publisher(array(data["publishers"]), "name", p.option.UseOriginalPublisher)
		setStatus(&item, text(data["status"]))
		positive(&item, "totalBookCount", data["final_volume"])
		tags, genres := []string{}, []string{}
		for _, value := range array(data["tags_v2"]) {
			tag := obj(value)
			if tag["is_genre"] == true {
				genres = append(genres, text(tag["name"]))
			} else {
				tags = append(tags, text(tag["name"]))
			}
		}
		item.Fields["genres"], item.Fields["tags"] = genres, tags
		item.Cover = first(text(child(data, "cover", "raw", "url")), text(child(data, "cover", "x350", "x1")))
		source(&item, "MangaBaka", "https://mangabaka.org/"+item.ID)
	}
	return item
}

func localizedTitles(item *Metadata, values object) {
	keys := make([]string, 0, len(values))
	for key := range values {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	for _, key := range keys {
		title(item, text(values[key]), key)
	}
}
func localized(values object, preferred string) string {
	for _, language := range []string{preferred, "en", "ja", "zh", "zh-hk"} {
		if text(values[language]) != "" {
			return text(values[language])
		}
	}
	keys := make([]string, 0, len(values))
	for key := range values {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	for _, key := range keys {
		if text(values[key]) != "" {
			return text(values[key])
		}
	}
	return ""
}
