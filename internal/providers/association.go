package providers

import (
	"regexp"
	"strconv"
	"strings"
)

var volumePatterns = []*regexp.Regexp{
	regexp.MustCompile(`(?i)(?:^|,?\s)\(?volume\s([0-9]+)(?:,?\s?[0-9]+,)+(\s?[0-9]+)\)?`),
	regexp.MustCompile(`(?i)(?:^|,?\s)\(?(?:[vt]|vols\.\s|vol\.\s|volume\s)([0-9]+(?:[.x#][0-9]+)?)(-[0-9]+(?:[.x#][0-9]+)?)?\)?`),
	regexp.MustCompile(`.*第\s*(\d+)\s*-?\s*(\d+)?\s*[巻卷册冊集]`),
	regexp.MustCompile(`.*年(?:[0-9]+月)?(?:[0-9]+日)?(\d+)-?(\d+)?号`),
}
var chapterPatterns = []*regexp.Regexp{
	regexp.MustCompile(`(?i)(?:^|\s?)(?:c|ch\.\s|chapter\s|ep\.\s)([0-9]+(?:[.x#][0-9]+)?)(-[0-9]+(?:[.x#][0-9]+)?)?`),
	regexp.MustCompile(`.*第\s*(\d+(?:\.\d+)?)\s*-?\s*(\d+(?:\.\d+)?)?\s*[話话章节]`),
}
var bookPatterns = []*regexp.Regexp{
	regexp.MustCompile(`(?i)(?:\s|#|no\.)([0-9]+[AB]?(?:[.x#][0-9]+)?)(-[0-9]+(?:[.x#][0-9]+)?)?(?:\s\(.*\)\s*)*$`),
	regexp.MustCompile(`Issue ([0-9]+[AB]?(?:[.x#][0-9]+)?)(-[0-9]+(?:[.x#][0-9]+)?)?`),
	regexp.MustCompile(`Volume ([0-9]+[AB]?(?:[.x#][0-9]+)?)(-[0-9]+(?:[.x#][0-9]+)?)?`),
}

func extractRange(name string, patterns []*regexp.Regexp, last bool) *BookRange {
	for _, pattern := range patterns {
		all := pattern.FindAllStringSubmatch(name, -1)
		if len(all) == 0 {
			continue
		}
		captures := all[0]
		if last {
			captures = all[len(all)-1]
		}
		normalize := strings.NewReplacer("x", ".", "#", ".", "-", "")
		start, err := strconv.ParseFloat(normalize.Replace(captures[1]), 64)
		if err != nil {
			return nil
		}
		end, err := strconv.ParseFloat(normalize.Replace(captures[2]), 64)
		if err != nil {
			end = start
		}
		return &BookRange{start, end}
	}
	return nil
}

func parseBookRange(name, media string) *BookRange {
	if media == "comic" {
		return extractRange(name, volumePatterns, false)
	}
	if media == "webtoon" {
		if result := extractRange(name, chapterPatterns, true); result != nil {
			return result
		}
	}
	return extractRange(name, bookPatterns, true)
}

type LocalBook struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

func Associate(local []LocalBook, remote []SeriesBook, media string) map[string]string {
	result := map[string]string{}
	if len(local) == 1 && len(remote) == 1 {
		if extractRange(local[0].Name, chapterPatterns, true) == nil {
			result[local[0].ID] = remote[0].ID
		}
		return result
	}
	extra := regexp.MustCompile(`\[(.*?)\]`)
	for _, book := range local {
		number := parseBookRange(book.Name, media)
		if number == nil {
			continue
		}
		edition := ""
		for _, bracket := range extra.FindAllStringSubmatch(book.Name, -1) {
			for _, candidate := range remote {
				if candidate.Edition != "" && strings.EqualFold(bracket[1], candidate.Edition) {
					edition = candidate.Edition
					break
				}
			}
		}
		for _, candidate := range remote {
			if candidate.Edition == edition && candidate.Number != nil && *candidate.Number == *number {
				result[book.ID] = candidate.ID
				break
			}
		}
	}
	return result
}
