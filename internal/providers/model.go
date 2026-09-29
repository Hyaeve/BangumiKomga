// Package providers ports the provider boundary from komf-rs.
// See THIRD_PARTY_NOTICES.md for the upstream license and attribution.
package providers

import (
	"context"
	"fmt"
	"sort"
	"strings"
)

type Options struct {
	Name                 string          `json:"name"`
	Enabled              bool            `json:"enabled"`
	Priority             int             `json:"priority"`
	APIKey               string          `json:"api_key,omitempty"`
	Token                string          `json:"token,omitempty"`
	Database             string          `json:"database,omitempty"`
	MatchingMode         string          `json:"matching_mode,omitempty"`
	Fields               map[string]bool `json:"fields,omitempty"`
	TagWhitelist         []string        `json:"tag_whitelist,omitempty"`
	TagsScoreThreshold   *int            `json:"tags_score_threshold,omitempty"`
	TagsSizeLimit        *int            `json:"tags_size_limit,omitempty"`
	UseOriginalPublisher bool            `json:"use_original_publisher,omitempty"`
	TitleLanguage        string          `json:"title_language,omitempty"`
	BookFields           map[string]bool `json:"book_fields,omitempty"`
	IDFormat             string          `json:"id_format,omitempty"`
	GIDOnly              bool            `json:"gid_only,omitempty"`
	Languages            []string        `json:"languages,omitempty"`
	CoverLanguages       []string        `json:"cover_languages,omitempty"`
	AuthorRoles          []string        `json:"author_roles,omitempty"`
	ArtistRoles          []string        `json:"artist_roles,omitempty"`
}

type Config struct {
	Providers []Options `json:"providers"`
	Proxy     string    `json:"proxy,omitempty"`
}

type Title struct {
	Name     string `json:"name"`
	Language string `json:"language,omitempty"`
}

type Metadata struct {
	Provider string         `json:"provider"`
	ID       string         `json:"id"`
	Media    string         `json:"media_type"`
	Titles   []Title        `json:"titles"`
	Fields   map[string]any `json:"fields"`
	Cover    string         `json:"cover,omitempty"`
	Raw      map[string]any `json:"-"`
}

type MatchContext struct {
	StartYear int    `json:"start_year,omitempty"`
	Folder    string `json:"folder,omitempty"`
	BookName  string `json:"book_name,omitempty"`
	BookFile  string `json:"book_file,omitempty"`
	OneShot   bool   `json:"oneshot,omitempty"`
	CoverPath string `json:"cover_path,omitempty"`
}

type MatchResult struct {
	Match  *Metadata `json:"match"`
	Errors []string  `json:"errors"`
	Query  string    `json:"query,omitempty"`
}

type Provider interface {
	Name() string
	Search(context.Context, string, string) ([]Metadata, error)
	Get(context.Context, string) (Metadata, error)
}

type registered struct {
	provider Provider
	options  Options
}

// Registration order is retained for equal priorities, as in ProvidersModule.
var registration = []string{"MANGA_UPDATES", "MAL", "ANILIST", "MANGADEX",
	"COMIC_VINE", "MANGA_BAKA", "BOOK_WALKER", "YEN_PRESS", "VIZ", "WEBTOONS", "EHENTAI"}

var priorities = map[string]int{"MANGA_UPDATES": 10, "MAL": 20, "ANILIST": 40,
	"MANGADEX": 10, "COMIC_VINE": 110, "MANGA_BAKA": 10, "BOOK_WALKER": 10,
	"YEN_PRESS": 50, "VIZ": 70, "WEBTOONS": 130, "EHENTAI": 10}

func Catalog() []Options {
	result := make([]Options, 0, len(registration))
	for _, name := range registration {
		result = append(result, Options{Name: name, Priority: priorities[name], Enabled: name == "MANGA_UPDATES"})
	}
	return result
}

func (c Config) registry() ([]registered, error) {
	options := map[string]Options{}
	for _, item := range c.Providers {
		if _, ok := priorities[item.Name]; !ok {
			return nil, fmt.Errorf("unknown provider %q", item.Name)
		}
		if _, duplicate := options[item.Name]; duplicate {
			return nil, fmt.Errorf("duplicate provider %s", item.Name)
		}
		if item.MatchingMode != "" && item.MatchingMode != "EXACT" && item.MatchingMode != "CLOSEST_MATCH" {
			return nil, fmt.Errorf("invalid matching mode for %s", item.Name)
		}
		options[item.Name] = item
	}
	client, err := newClient(c.Proxy)
	if err != nil {
		return nil, err
	}
	result := []registered{}
	for _, name := range registration {
		option, exists := options[name]
		if !exists || !option.Enabled {
			continue
		}
		result = append(result, registered{&remoteProvider{option: option, client: client}, option})
	}
	sort.SliceStable(result, func(i, j int) bool { return result[i].options.Priority < result[j].options.Priority })
	return result, nil
}

func Match(ctx context.Context, config Config, queries []string, media string) (MatchResult, error) {
	return MatchWithContext(ctx, config, queries, media, MatchContext{})
}

func MatchWithContext(ctx context.Context, config Config, queries []string, media string, context MatchContext) (MatchResult, error) {
	if media != "comic" && media != "book" && media != "mixed" {
		return MatchResult{}, fmt.Errorf("invalid media type")
	}
	registry, err := config.registry()
	if err != nil {
		return MatchResult{}, err
	}
	return matchRegisteredWithContext(ctx, registry, queries, media, context), nil
}

func matchRegistered(ctx context.Context, registry []registered, queries []string, media string) MatchResult {
	return matchRegisteredWithContext(ctx, registry, queries, media, MatchContext{})
}

func matchRegisteredWithContext(ctx context.Context, registry []registered, queries []string, media string, context MatchContext) MatchResult {
	result := MatchResult{Errors: []string{}}
	for _, entry := range registry {
		for _, query := range unique(queries) {
			if ctx.Err() != nil {
				result.Errors = append(result.Errors, "provider matching cancelled or timed out")
				return result
			}
			if id := resolveLink(entry.provider.Name(), query); id != "" {
				detail, err := entry.provider.Get(ctx, id)
				if err != nil {
					result.Errors = append(result.Errors, entry.provider.Name()+": "+err.Error())
					// Like komf, failed direct identification still permits search.
				} else if mediaAllowed(media, detail.Media) {
					filterMetadata(&detail, entry.options)
					result.Match, result.Query = &detail, query
					return result
				}
			}
			if native, ok := entry.provider.(*remoteProvider); ok {
				detail, err := native.match(ctx, query, media, context)
				if err != nil {
					result.Errors = append(result.Errors, entry.provider.Name()+": "+err.Error())
				} else if detail != nil {
					filterMetadata(detail, entry.options)
					result.Match, result.Query = detail, query
					return result
				}
				continue
			}
			candidates, err := entry.provider.Search(ctx, query, media)
			if err != nil {
				result.Errors = append(result.Errors, entry.provider.Name()+": "+err.Error())
				continue
			}
			if entry.provider.Name() == "COMIC_VINE" {
				matching := 0
				for _, candidate := range candidates {
					if mediaAllowed(media, candidate.Media) && matches(query, candidate.Titles, entry.options.MatchingMode) {
						matching++
					}
				}
				// The reference disambiguates multiple matches using book covers.
				// Without that context, do not silently choose the first volume.
				if matching > 1 {
					result.Errors = append(result.Errors, "COMIC_VINE: ambiguous matches require book/cover context")
					continue
				}
			}
			for _, candidate := range candidates {
				if !mediaAllowed(media, candidate.Media) || !matches(query, candidate.Titles, entry.options.MatchingMode) {
					continue
				}
				detail, err := entry.provider.Get(ctx, candidate.ID)
				if err != nil {
					result.Errors = append(result.Errors, entry.provider.Name()+": "+err.Error())
					continue
				}
				if !mediaAllowed(media, detail.Media) {
					continue
				}
				filterMetadata(&detail, entry.options)
				if len(detail.Titles) == 0 || len(detail.Fields) == 0 {
					continue
				}
				result.Match, result.Query = &detail, query
				return result
			}
		}
	}
	return result
}

func Get(ctx context.Context, config Config, name, id string) (Metadata, error) {
	registry, err := config.registry()
	if err != nil {
		return Metadata{}, err
	}
	for _, entry := range registry {
		if entry.provider.Name() == name {
			detail, err := entry.provider.Get(ctx, id)
			if err == nil {
				filterMetadata(&detail, entry.options)
			}
			return detail, err
		}
	}
	return Metadata{}, fmt.Errorf("provider %s is disabled", name)
}

// Search exposes candidates for an explicit user choice, not automatic matching.
func Search(ctx context.Context, config Config, name, query, media string) ([]Metadata, error) {
	if media != "comic" && media != "book" && media != "mixed" {
		return nil, fmt.Errorf("invalid media type")
	}
	query = strings.TrimSpace(query)
	if query == "" || len([]rune(query)) > 200 {
		return nil, fmt.Errorf("search query must contain 1 to 200 characters")
	}
	registry, err := config.registry()
	if err != nil {
		return nil, err
	}
	for _, entry := range registry {
		if entry.provider.Name() != name {
			continue
		}
		items, err := entry.provider.Search(ctx, query, media)
		if err != nil {
			return nil, err
		}
		result := []Metadata{}
		for _, item := range items {
			if !mediaAllowed(media, item.Media) {
				continue
			}
			filterMetadata(&item, entry.options)
			result = append(result, item)
			if len(result) == 30 {
				break
			}
		}
		return result, nil
	}
	return nil, fmt.Errorf("provider %s is unavailable", name)
}

func mediaAllowed(wanted, actual string) bool {
	return (actual == "comic" || actual == "book") && (wanted == "mixed" || wanted == actual)
}

func unique(values []string) []string {
	result, seen := []string{}, map[string]bool{}
	for _, value := range values {
		value = strings.TrimSpace(value)
		if value != "" && !seen[value] {
			seen[value] = true
			result = append(result, value)
		}
	}
	return result
}

func truncate(value string, limit int) string {
	runes := []rune(value)
	if len(runes) > limit {
		return string(runes[:limit])
	}
	return value
}
