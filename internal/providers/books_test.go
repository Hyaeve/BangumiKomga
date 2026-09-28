package providers

import (
	"context"
	"testing"
)

func TestReferenceBookAssociation(t *testing.T) {
	remote := []SeriesBook{
		{ID: "v1", Number: &BookRange{1, 1}},
		{ID: "v23", Number: &BookRange{2, 3}},
		{ID: "omni", Edition: "omnibus", Number: &BookRange{1, 1}},
	}
	local := []LocalBook{{"a", "Series Vol. 1"}, {"b", "Series 第2-3卷"}, {"c", "Series 第1话"}, {"d", "Series Vol. 1 [Omnibus]"}, {"e", "Unknown"}}
	matches := Associate(local, remote, "comic")
	if len(matches) != 3 || matches["a"] != "v1" || matches["b"] != "v23" || matches["d"] != "omni" {
		t.Fatal(matches)
	}
	if len(Associate([]LocalBook{{"a", "Oneshot"}}, remote[:1], "comic")) != 1 {
		t.Fatal("oneshot not associated")
	}
	if len(Associate(local[2:3], remote[:1], "comic")) != 0 {
		t.Fatal("chapter incorrectly treated as oneshot volume")
	}
	if parseBookRange("Book #2", "book").Start != 2 || parseBookRange("Title Chapter 10-12", "webtoon").End != 12 {
		t.Fatal("book/chapter range")
	}
}

func TestMangaDexCoverLanguageVolumeAssociation(t *testing.T) {
	p, _ := apiFixture(t, "MANGADEX", `{"total":4,"data":[
		{"attributes":{"volume":"1","locale":"ja","fileName":"ja.jpg"}},
		{"attributes":{"volume":"1","locale":"en","fileName":"en.jpg"}},
		{"attributes":{"volume":"2","locale":"ja","fileName":"two.jpg"}},
		{"attributes":{"volume":"3","locale":"de","fileName":"de.jpg"}}]}`)
	books, err := p.books(context.Background(), "series")
	if err != nil || len(books) != 2 || books[0].ID != "en.jpg" || books[1].ID != "two.jpg" {
		t.Fatalf("%+v %v", books, err)
	}
}

func TestComicVineBookRejectsWrongSeries(t *testing.T) {
	p, _ := apiFixture(t, "COMIC_VINE", `{"status_code":1,"results":{"id":3,"name":"Issue","volume":{"id":2}}}`)
	if _, err := p.book(context.Background(), "1", "3"); err == nil {
		t.Fatal("cross series write allowed")
	}
}

func TestWebtoonsEpisodeMetadata(t *testing.T) {
	p, _ := apiFixture(t, "WEBTOONS", `{"result":{"episodeList":[{"episodeNo":9,"episodeTitle":"Chapter","viewerLink":"/en/title/viewer?episode_no=9","thumbnail":"/cover.jpg","exposureDateMillis":1704067200000}]}}`)
	item, err := p.book(context.Background(), "/en/test/list?title_no=1", "/en/title/viewer?episode_no=9")
	if err != nil || item.Fields["number"] != "1" || item.Fields["releaseDate"] != "2024-01-01" {
		t.Fatalf("%+v %v", item, err)
	}
}
