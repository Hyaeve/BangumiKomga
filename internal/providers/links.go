package providers

import (
	"net/url"
	"regexp"
	"strings"
)

// Only recognized public provider hosts become direct IDs, never arbitrary URLs.
func resolveLink(provider, query string) string {
	address, err := url.Parse(strings.TrimSpace(query))
	if err != nil || (address.Scheme != "https" && address.Scheme != "http") || address.User != nil || address.Port() != "" {
		return ""
	}
	host := strings.TrimPrefix(strings.ToLower(address.Hostname()), "www.")
	path := strings.Trim(address.Path, "/")
	parts := strings.Split(path, "/")
	numeric := regexp.MustCompile(`^[0-9]+$`)
	switch provider {
	case "ANILIST":
		if host == "anilist.co" && len(parts) >= 2 && parts[0] == "manga" && numeric.MatchString(parts[1]) {
			return parts[1]
		}
	case "MAL":
		if host == "myanimelist.net" && len(parts) >= 2 && parts[0] == "manga" && numeric.MatchString(parts[1]) {
			return parts[1]
		}
	case "MANGADEX":
		if host == "mangadex.org" && len(parts) >= 2 && parts[0] == "title" {
			return parts[1]
		}
	case "MANGA_UPDATES":
		if host == "mangaupdates.com" {
			if len(parts) >= 2 && parts[0] == "series" && numeric.MatchString(parts[1]) {
				return parts[1]
			}
			if path == "series.html" && numeric.MatchString(address.Query().Get("id")) {
				return address.Query().Get("id")
			}
		}
	case "MANGA_BAKA":
		if host == "mangabaka.org" && len(parts) >= 1 && numeric.MatchString(parts[0]) {
			return parts[0]
		}
	case "COMIC_VINE":
		if host == "comicvine.gamespot.com" {
			for _, part := range parts {
				if strings.HasPrefix(part, "4050-") && numeric.MatchString(strings.TrimPrefix(part, "4050-")) {
					return strings.TrimPrefix(part, "4050-")
				}
			}
		}
	case "YEN_PRESS":
		if host == "yenpress.com" && len(parts) == 2 && parts[0] == "series" {
			return parts[1]
		}
	case "BOOK_WALKER":
		if host == "bookwalker.com" && len(parts) >= 2 && parts[0] == "series" {
			return parts[1]
		}
	case "VIZ":
		if host == "viz.com" && strings.HasPrefix(path, "manga-books/manga/") {
			return strings.TrimPrefix(path, "manga-books/manga/")
		}
	case "WEBTOONS":
		if host == "webtoons.com" && strings.HasPrefix(path, "en/") && strings.HasSuffix(path, "/list") && numeric.MatchString(address.Query().Get("title_no")) {
			return "/" + path + "?title_no=" + address.Query().Get("title_no")
		}
	case "EHENTAI":
		if (host == "e-hentai.org" || host == "exhentai.org") && len(parts) == 3 && parts[0] == "g" && numeric.MatchString(parts[1]) && regexp.MustCompile(`^[a-f0-9]+$`).MatchString(parts[2]) {
			return parts[1] + ";" + parts[2]
		}
	}
	return ""
}
