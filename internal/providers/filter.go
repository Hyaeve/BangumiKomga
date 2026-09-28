package providers

import (
	"html"
	"net/url"
	"reflect"
	"strings"
	"unicode"

	"github.com/PuerkitoBio/goquery"
)

// Mirrors NameSimilarityMatcher: <=3 characters exact, then edit distances 1/2/3.
func matches(query string, titles []Title, mode string) bool {
	query = strings.TrimSpace(query)
	if query == "" {
		return false
	}
	length := len([]rune(query))
	for _, title := range titles {
		name := strings.TrimSpace(html.UnescapeString(title.Name))
		if mode == "EXACT" || length <= 3 {
			if query == name {
				return true
			}
			continue
		}
		threshold := 3
		if length <= 6 {
			threshold = 1
		} else if length <= 9 {
			threshold = 2
		}
		a, b := []rune(strings.ToUpper(query)), []rune(strings.ToUpper(name))
		if len(b) > len(a)+threshold || len(a) > len(b)+threshold {
			continue
		}
		cost := make([]int, len(a)+1)
		for i := range cost {
			cost[i] = i
		}
		for i, char := range b {
			next := make([]int, len(a)+1)
			next[0] = i + 1
			for j, other := range a {
				substitution := 1
				if char == other {
					substitution = 0
				}
				next[j+1] = min(cost[j]+substitution, cost[j+1]+1, next[j]+1)
			}
			cost = next
		}
		if cost[len(a)] <= threshold {
			return true
		}
	}
	return false
}

func plain(value string) string {
	doc, err := goquery.NewDocumentFromReader(strings.NewReader(value))
	if err != nil {
		return strings.TrimSpace(html.UnescapeString(value))
	}
	doc.Find("script,style,noscript").Remove()
	doc.Find("br").ReplaceWithHtml("\n")
	doc.Find("p,div,li").Each(func(_ int, s *goquery.Selection) { s.AppendHtml("\n") })
	lines := []string{}
	for _, line := range strings.Split(doc.Text(), "\n") {
		if line = strings.Join(strings.Fields(line), " "); line != "" {
			lines = append(lines, line)
		}
	}
	return strings.Join(lines, "\n")
}

func filterMetadata(item *Metadata, option Options) {
	titles, seen := []Title{}, map[string]bool{}
	for _, title := range item.Titles {
		title.Name = strings.TrimSpace(html.UnescapeString(title.Name))
		key := strings.ToLower(strings.Map(func(r rune) rune {
			if unicode.IsSpace(r) {
				return -1
			}
			return r
		}, title.Name))
		if key != "" && !seen[key] {
			seen[key] = true
			titles = append(titles, title)
		}
	}
	item.Titles = titles
	if item.Fields == nil {
		item.Fields = map[string]any{}
	}
	if len(titles) > 0 {
		chosen := titles[0]
		for _, title := range titles {
			if option.TitleLanguage != "" && strings.EqualFold(option.TitleLanguage, title.Language) {
				chosen = title
				break
			}
		}
		item.Fields["title"] = chosen.Name
		alternates := []map[string]string{}
		for _, title := range titles {
			if title.Name != chosen.Name {
				label := title.Language
				if label == "" {
					label = item.Provider
				}
				alternates = append(alternates, map[string]string{"label": label, "title": title.Name})
			}
		}
		if len(alternates) > 0 {
			item.Fields["alternateTitles"] = alternates
		}
	}
	for key, value := range item.Fields {
		if enabled, exists := option.Fields[key]; exists && !enabled {
			delete(item.Fields, key)
			continue
		}
		switch value := value.(type) {
		case string:
			value = strings.TrimSpace(value)
			if key == "summary" {
				value = plain(value)
			}
			if value == "" {
				delete(item.Fields, key)
			} else {
				item.Fields[key] = value
			}
		case []string:
			value = unique(value)
			if len(value) == 0 {
				delete(item.Fields, key)
			} else {
				item.Fields[key] = value
			}
		case nil:
			delete(item.Fields, key)
		}
		if value != nil && reflect.TypeOf(value).Kind() == reflect.Slice && reflect.ValueOf(value).Len() == 0 {
			delete(item.Fields, key)
		}
	}
	if links, ok := item.Fields["links"].([]map[string]string); ok {
		valid, seen := []map[string]string{}, map[string]bool{}
		for _, link := range links {
			address, err := url.Parse(link["url"])
			if err == nil && address.Hostname() != "" && address.User == nil &&
				(address.Scheme == "https" || address.Scheme == "http") && !seen[link["label"]] {
				seen[link["label"]] = true
				valid = append(valid, link)
			}
		}
		if len(valid) == 0 {
			delete(item.Fields, "links")
		} else {
			item.Fields["links"] = valid
		}
	}
	if enabled, exists := option.Fields["thumbnail"]; exists && !enabled {
		item.Cover = ""
	}
}
