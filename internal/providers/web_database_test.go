package providers

import (
	"context"
	"database/sql"
	"path/filepath"
	"strings"
	"testing"
)

func TestWebProviders(t *testing.T) {
	t.Run("VIZ", func(t *testing.T) {
		p, _ := apiFixture(t, "VIZ",
			`<div id="results"><a href="/manga-books/manga/test-volume-1/product/42">Test, Vol. 1</a><a href="/manga-books/manga/test-volume-2/product/43">Test, Vol. 2</a></div>`,
			`<div id="product_row"><div id="product_image_block"><img src="https://example.com/cover.jpg"></div><div><div id="purchase_links_block"><h2>Test, Vol. 1</h2></div><div>Summary</div></div></div>`)
		hits, err := p.Search(context.Background(), "Test", "comic")
		if err != nil || len(hits) != 1 {
			t.Fatalf("search: %+v %v", hits, err)
		}
		item, err := p.Get(context.Background(), hits[0].ID)
		if err != nil || item.Titles[0].Name != "Test" {
			t.Fatalf("detail: %+v %v", item, err)
		}
	})
	t.Run("WEBTOONS", func(t *testing.T) {
		p, _ := apiFixture(t, "WEBTOONS",
			`{"success":true,"result":{"webtoonResult":{"titleList":[{"titleNo":42,"title":"Test","titleGroupName":"test","representGenre":"fantasy"}]}}}`,
			`{"success":true,"result":{"challengeResult":{"titleList":[]}}}`,
			`<h1 class="subj">Test</h1><div id="_asideDetail"><p class="summary">Story</p><p class="day_info">COMPLETED</p></div>`)
		hits, err := p.Search(context.Background(), "Test", "comic")
		if err != nil || len(hits) != 1 {
			t.Fatalf("search: %+v %v", hits, err)
		}
		item, err := p.Get(context.Background(), hits[0].ID)
		if err != nil || item.Fields["status"] != "ENDED" {
			t.Fatalf("detail: %+v %v", item, err)
		}
	})
	t.Run("YEN_PRESS", func(t *testing.T) {
		p, _ := apiFixture(t, "YEN_PRESS",
			`{"results":[{"title":{"raw":"Test"},"url":{"raw":"/series/test"}}]}`,
			`<div class="inline_block"><a href="/titles/test-one"><img><span>Test, Vol. 1</span></a></div>`,
			`<div class="heading-content"><h1 class="heading">Test, Vol. 1</h1></div><div class="book-info"><div class="content-heading-txt"><h2>About</h2><p>Story</p></div></div>`)
		hits, err := p.Search(context.Background(), "Test", "comic")
		if err != nil || len(hits) != 1 {
			t.Fatalf("search: %+v %v", hits, err)
		}
		item, err := p.Get(context.Background(), hits[0].ID)
		if err != nil || item.Fields["summary"] != "Story" || item.Titles[0].Name != "Test" {
			t.Fatalf("detail: %+v %v", item, err)
		}
	})
	t.Run("EHENTAI", func(t *testing.T) {
		json := `{"gmetadata":[{"gid":42,"token":"abc","title":"[Group] Test [English]","title_jpn":"","tags":["language:english","female:test","parody:original","artist:ignore"]}]}`
		p, _ := apiFixture(t, "EHENTAI", `<a href="https://e-hentai.org/g/42/abc/">Test</a>`, json, json)
		hits, err := p.Search(context.Background(), "Test", "comic")
		if err != nil || len(hits) != 1 {
			t.Fatalf("search: %+v %v", hits, err)
		}
		item, err := p.Get(context.Background(), hits[0].ID)
		if err != nil || item.Fields["language"] != "en" || strings.Join(item.Fields["tags"].([]string), ",") != "test" {
			t.Fatalf("detail: %+v %v", item, err)
		}
	})
}

func TestProviderDatabases(t *testing.T) {
	for _, name := range []string{"BOOK_WALKER", "MANGA_BAKA"} {
		t.Run(name, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "source.sqlite")
			db, err := sql.Open("sqlite", path)
			if err != nil {
				t.Fatal(err)
			}
			if name == "BOOK_WALKER" {
				_, err = db.Exec(`CREATE TABLE series(id TEXT,type INTEGER,title TEXT,alt_titles TEXT,description TEXT);
				INSERT INTO series VALUES ('1',1,'Test','["Alias"]','Summary'),('2',2,'Test Novel','[]','Story');
				CREATE VIRTUAL TABLE series_fts USING fts5(id UNINDEXED,title,alt_titles,type UNINDEXED);
				INSERT INTO series_fts VALUES ('1','Test','Alias',1),('2','Test Novel','',2);
				CREATE TABLE tags(id INTEGER,name TEXT); INSERT INTO tags VALUES (1,'Action');
				CREATE TABLE series_tags(series_id TEXT,tag_id INTEGER); INSERT INTO series_tags VALUES ('1',1);`)
			} else {
				_, err = db.Exec(`CREATE TABLE series(id INTEGER,type TEXT,titles TEXT,description TEXT,status TEXT);
				INSERT INTO series VALUES (1,'manga','[{"title":"Test","language":"en"}]','Summary','completed');
				CREATE VIRTUAL TABLE titles_fts USING fts5(id UNINDEXED,title,type UNINDEXED);
				INSERT INTO titles_fts VALUES (1,'Test','manga');`)
			}
			if err != nil {
				t.Fatal(err)
			}
			db.Close()
			p := &remoteProvider{option: Options{Name: name, Database: path}}
			hits, err := p.Search(context.Background(), "Test", "comic")
			if err != nil || len(hits) != 1 {
				t.Fatalf("search: %+v %v", hits, err)
			}
			detail, err := p.Get(context.Background(), hits[0].ID)
			if err != nil || detail.Fields["summary"] != "Summary" {
				t.Fatalf("detail: %+v %v", detail, err)
			}
			if _, err = p.Search(context.Background(), `" OR *`, "comic"); err != nil {
				t.Fatal(err)
			}
		})
	}
}

func TestDirectLinks(t *testing.T) {
	if resolveLink("ANILIST", "https://anilist.co/manga/42/test") != "42" {
		t.Fatal("valid link rejected")
	}
	for _, value := range []string{"https://anilist.co.evil/manga/42", "http://localhost/manga/42", "https://secret@anilist.co/manga/42", "https://anilist.co:8443/manga/42"} {
		if resolveLink("ANILIST", value) != "" {
			t.Fatal("unsafe link accepted")
		}
	}
}
