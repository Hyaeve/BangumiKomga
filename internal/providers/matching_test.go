package providers

import (
	"context"
	"strings"
	"testing"
)

func TestReferenceProviderSpecificMatching(t *testing.T) {
	t.Run("anilist_search_is_complete_no_detail_request", func(t *testing.T) {
		p, calls := apiFixture(t, "ANILIST", `{"data":{"mediaSearch":{"media":[{"id":42,"format":"MANGA","title":{"english":"Test Manga"},"description":"Search metadata"}]}}}`)
		item, err := p.match(context.Background(), "Test Manga", "comic", MatchContext{})
		if err != nil || item == nil || item.Fields["summary"] != "Search metadata" || len(*calls) != 1 {
			t.Fatalf("match: %+v %v", item, err)
		}
	})
	t.Run("mal_no_second_title_gate", func(t *testing.T) {
		p, _ := apiFixture(t, "MAL", `{"data":[{"node":{"id":42,"title":"Test Manga","media_type":"manga"}}]}`,
			`{"id":42,"title":"Canonical title","media_type":"manga","synopsis":"Detail"}`)
		item, err := p.match(context.Background(), "Test Manga", "comic", MatchContext{})
		if err != nil || item == nil || item.Titles[0].Name != "Canonical title" {
			t.Fatalf("match: %+v %v", item, err)
		}
	})
	t.Run("comicvine_year_and_clean_query", func(t *testing.T) {
		p, calls := apiFixture(t, "COMIC_VINE", `{"status_code":1,"results":[{"id":1,"name":"Test Manga","start_year":"1999"},{"id":2,"name":"Test Manga","start_year":"2005"}]}`,
			`{"status_code":1,"results":{"id":2,"name":"Test Manga"}}`)
		item, err := p.match(context.Background(), "Test Manga (2005)", "comic", MatchContext{})
		if err != nil || item == nil || item.ID != "2" || (*calls)[0].URL.Query().Get("query") != "Test Manga" {
			t.Fatalf("match: %+v %v", item, err)
		}
	})
	t.Run("comicvine_folder_id_precedes_search", func(t *testing.T) {
		p, calls := apiFixture(t, "COMIC_VINE", `{"status_code":1,"results":{"id":42,"name":"Test"}}`)
		p.option.IDFormat = "[CV:{id}]"
		item, err := p.match(context.Background(), "Unknown", "comic", MatchContext{Folder: "Folder [CV:42]"})
		if err != nil || item == nil || item.ID != "42" || len(*calls) != 1 {
			t.Fatalf("match: %+v %v", item, err)
		}
	})
	t.Run("bookwalker_preserves_reference_list_comparison", func(t *testing.T) {
		if matches("Test", []Title{{Name: "Test[Alias]"}}, "") {
			t.Fatal("must not replace reference title+list matching with aliases")
		}
	})
	t.Run("viz_invalid_input_performs_no_network", func(t *testing.T) {
		p, calls := apiFixture(t, "VIZ")
		item, err := p.match(context.Background(), "123--test", "comic", MatchContext{})
		if err != nil || item != nil || len(*calls) != 0 {
			t.Fatal("invalid query fetched")
		}
	})
}

func TestTitleVariantsFromReference(t *testing.T) {
	if yenTitle("My Series (manga), Vol. 3") != "My Series" {
		t.Fatal("YenPress title suffix")
	}
	if strings.Join(ehQueries("[C] Series (Vol. 1) [en]"), "|") != "[C] Series (Vol. 1) [en]|Series" {
		t.Fatal(ehQueries("[C] Series (Vol. 1) [en]"))
	}
}
