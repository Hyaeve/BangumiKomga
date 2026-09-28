package providers

import (
	"context"
	"regexp"
	"sort"
	"strconv"
	"strings"
)

var parentheses = regexp.MustCompile(`[(\[{]([^)}\]]+)[)}\]]`)
var startYear = regexp.MustCompile(`\(([0-9]{4})(-[0-9]{4})?\)`)
var vizInvalid = regexp.MustCompile(`^[0-9]+--`)
var vizParentheses = regexp.MustCompile(`\([^)]+\)`)
var yenKind = regexp.MustCompile(`\(light novel\)|\(manga\)`)
var yenVolume = regexp.MustCompile(`, Vol\. [0-9]+`)
var ehGID = regexp.MustCompile(`(?:\[|\()?([0-9]{5,})(?:\]|\))?\s*$`)
var ehTrailing = regexp.MustCompile(`(?:\s*\[[^\]]*\])+$`)
var ehLeading = regexp.MustCompile(`^(?:\([^)]*\)\s*)?(?:\[[^\]]*\]\s*)`)
var ehRemnants = regexp.MustCompile(`\[[^\[\]]*\]|（[^（）]*）|\([^()]*\)`)
var ehCore = regexp.MustCompile(`(?:\s*[（(][^)）]+[)）])+$`)
var ehDate = regexp.MustCompile(`^[\d\-.\s]+$`)
var ehPlatform = regexp.MustCompile(`(?i)^\[(?:pixiv|fanbox|fantia|patreon|gumroad|dlsite)`)

func yenTitle(name string) string {
	return strings.TrimSpace(yenVolume.ReplaceAllString(strings.TrimSpace(yenKind.ReplaceAllString(name, "")), ""))
}

func ehQueries(name string) []string {
	base := strings.TrimSpace(ehTrailing.ReplaceAllString(name, ""))
	cleaned := strings.TrimSpace(ehLeading.ReplaceAllString(base, ""))
	reverted := ehDate.MatchString(cleaned) || ehPlatform.MatchString(name)
	if reverted {
		cleaned = base
	}
	parts := strings.Split(cleaned, "|")
	best := strings.TrimSpace(parts[len(parts)-1])
	if !reverted {
		if stripped := strings.Join(strings.Fields(ehRemnants.ReplaceAllString(best, " ")), " "); stripped != "" {
			best = stripped
		}
	}
	if best == "" {
		best = name
	}
	return unique([]string{name, best, ehCore.ReplaceAllString(best, "")})
}

// Each provider follows its own match_series_metadata method, not a second
// generic ranking pass. Search DTOs and detail DTOs need not have the same title.
func (p *remoteProvider) match(ctx context.Context, query, media string, context MatchContext) (*Metadata, error) {
	search, comparison := query, query
	switch p.Name() {
	case "ANILIST", "MANGADEX", "MANGA_BAKA", "WEBTOONS":
		search = truncate(query, 400)
	case "YEN_PRESS":
		search = truncate(query, 128)
	case "VIZ":
		if vizInvalid.MatchString(query) {
			return nil, nil
		}
		search = strings.TrimSpace(vizParentheses.ReplaceAllString(truncate(query, 100), ""))
	case "COMIC_VINE":
		if p.option.IDFormat != "" {
			parts := strings.SplitN(p.option.IDFormat, "{id}", 2)
			if len(parts) == 2 {
				pattern := regexp.MustCompile(regexp.QuoteMeta(parts[0]) + `([0-9]+)` + regexp.QuoteMeta(parts[1]))
				for _, value := range []string{context.Folder, query} {
					if id := pattern.FindStringSubmatch(value); len(id) == 2 {
						item, err := p.Get(ctx, id[1])
						return &item, err
					}
				}
			}
		}
		comparison = strings.TrimSpace(parentheses.ReplaceAllString(query, ""))
		search = truncate(strings.ReplaceAll(comparison, "<", ""), 400)
	case "EHENTAI":
		return p.matchGallery(ctx, query, media, context)
	}
	candidates, err := p.Search(ctx, search, media)
	if err != nil {
		return nil, err
	}
	if p.Name() == "WEBTOONS" && len(candidates) > 5 {
		candidates = candidates[:5]
	}
	var selected []Metadata
	for _, candidate := range candidates {
		titles := candidate.Titles
		switch p.Name() {
		case "MANGA_UPDATES", "COMIC_VINE":
			if len(titles) > 1 {
				titles = titles[:1]
			}
		case "BOOK_WALKER":
			// Keep the reference's single title+List.toString() comparison.
			titles = []Title{{Name: text(candidate.Raw["title"]) + "[" + strings.Join(stringsIn(candidate.Raw["alt_titles"]), ", ") + "]"}}
		case "YEN_PRESS":
			titles = []Title{{Name: yenTitle(titles[0].Name)}}
		}
		if !mediaAllowed(media, candidate.Media) || !matches(comparison, titles, p.option.MatchingMode) {
			continue
		}
		if p.Name() == "COMIC_VINE" {
			year := context.StartYear
			if year == 0 {
				if match := startYear.FindStringSubmatch(query); len(match) > 1 {
					year, _ = strconv.Atoi(match[1])
				}
			}
			if candidate.Raw["start_year"] != nil && year != 0 && text(candidate.Raw["start_year"]) != strconv.Itoa(year) {
				continue
			}
			selected = append(selected, candidate)
			continue
		}
		switch p.Name() {
		case "ANILIST", "MANGA_BAKA", "MANGADEX":
			return &candidate, nil
		default:
			// komf selects the first search match, then gets its metadata.
			// A detail failure does not silently select a different series.
			item, err := p.Get(ctx, candidate.ID)
			return &item, err
		}
	}
	if len(selected) == 1 {
		item, err := p.Get(ctx, selected[0].ID)
		return &item, err
	}
	for _, candidate := range selected {
		matched, err := p.coverMatch(ctx, candidate, context)
		if err != nil {
			return nil, err
		}
		if matched {
			item, err := p.Get(ctx, candidate.ID)
			return &item, err
		}
	}
	return nil, nil
}

func (p *remoteProvider) matchGallery(ctx context.Context, query, media string, context MatchContext) (*Metadata, error) {
	if media == "book" {
		return nil, nil
	}
	gidTitles := []string{query, context.Folder}
	if context.OneShot {
		gidTitles = append(gidTitles, context.BookName, context.BookFile)
	}
	for _, value := range gidTitles {
		if match := ehGID.FindStringSubmatch(value); len(match) > 1 {
			items, err := p.Search(ctx, "gid:"+match[1], media)
			if err != nil {
				return nil, err
			}
			for _, item := range items {
				if strings.Split(item.ID, ";")[0] == match[1] {
					return &item, nil
				}
			}
			break
		}
	}
	if p.option.GIDOnly {
		return nil, nil
	}
	name := first(context.BookName, query)
	items, seen := []Metadata{}, map[string]bool{}
	for _, variant := range ehQueries(name) {
		found, err := p.Search(ctx, truncate(variant, 400), media)
		if err != nil {
			return nil, err
		}
		for _, item := range found {
			if !seen[item.ID] {
				seen[item.ID] = true
				items = append(items, item)
			}
		}
	}
	// Explicit translated-language markers take precedence, then normal order.
	forced := ""
	if strings.Contains(name, "中国翻訳") {
		forced = "zh"
	} else if strings.Contains(name, "英訳") {
		forced = "en"
	}
	languages := p.option.Languages
	if languages == nil {
		languages = []string{"zh", "ja"}
	}
	ordered := []Metadata{}
	for _, language := range append(append([]string{}, languages...), "") {
		group := []Metadata{}
		for _, item := range items {
			if text(item.Fields["language"]) == language {
				group = append(group, item)
			}
		}
		sort.SliceStable(group, func(i, j int) bool { return decimal(group[i].Raw["rating"]) > decimal(group[j].Raw["rating"]) })
		ordered = append(ordered, group...)
	}
	if len(languages) > 0 && len(ordered) > 0 {
		items = ordered
	}
	for _, language := range []string{forced, ""} {
		for _, item := range items {
			if language != "" && text(item.Fields["language"]) != language {
				continue
			}
			for _, remote := range []string{text(item.Raw["title"]), text(item.Raw["title_jpn"])} {
				for _, local := range ehQueries(name) {
					for _, candidate := range ehQueries(remote) {
						if matches(local, []Title{{Name: candidate}}, p.option.MatchingMode) {
							return &item, nil
						}
					}
				}
			}
		}
	}
	return nil, nil
}

func decimal(value any) float64 {
	result, _ := strconv.ParseFloat(text(value), 64)
	return result
}
