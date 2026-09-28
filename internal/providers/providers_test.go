package providers

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"
	"testing"
)

type roundTrip func(*http.Request) (*http.Response, error)

func (f roundTrip) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func apiFixture(t *testing.T, name string, fixtures ...string) (*remoteProvider, *[]*http.Request) {
	t.Helper()
	calls := []*http.Request{}
	index := 0
	p := &remoteProvider{option: Options{Name: name, Enabled: true, APIKey: "private-key"}}
	p.client = &http.Client{Transport: roundTrip(func(r *http.Request) (*http.Response, error) {
		calls = append(calls, r)
		if index >= len(fixtures) {
			t.Fatalf("unexpected request %s", r.URL.Path)
		}
		body := fixtures[index]
		index++
		return &http.Response{StatusCode: 200, Body: io.NopCloser(strings.NewReader(body)), Header: http.Header{}}, nil
	})}
	return p, &calls
}

func TestAPIProvidersSearchAndDetails(t *testing.T) {
	fixtures := []struct{ name, search, detail, id, media string }{
		{"MANGA_UPDATES", `{"results":[{"record":{"series_id":42,"title":"Test Manga"}}]}`,
			`{"series_id":42,"title":"Test Manga","type":"Manga","description":"<p>Summary</p>","categories":[{"category":"Low","votes":1},{"category":"High","votes":100}]}`, "42", "comic"},
		{"ANILIST", `{"data":{"mediaSearch":{"media":[{"id":42,"format":"MANGA","title":{"romaji":"Test Manga"}}]}}}`,
			`{"data":{"Media":{"id":42,"format":"MANGA","title":{"romaji":"Test Manga"},"tags":[{"name":"low","rank":20},{"name":"high","rank":90}]}}}`, "42", "comic"},
		{"MAL", `{"data":[{"node":{"id":42,"title":"Test Novel","media_type":"light_novel"}}]}`,
			`{"id":42,"title":"Test Novel","media_type":"light_novel","synopsis":"Summary","num_volumes":5}`, "42", "book"},
		{"MANGADEX", `{"result":"ok","data":[{"id":"abc","attributes":{"title":{"en":"Test Manga"}}}]}`,
			`{"result":"ok","data":{"id":"abc","attributes":{"title":{"en":"Test Manga"},"publicationDemographic":"Shounen","tags":[{"attributes":{"group":"genre","name":{"en":"Action"}}},{"attributes":{"group":"theme","name":{"en":"School"}}},{"attributes":{"group":"format","name":{"en":"Ignored"}}}]}}}`, "abc", "comic"},
		{"COMIC_VINE", `{"status_code":1,"results":[{"id":42,"name":"Test Comic"}]}`,
			`{"status_code":1,"results":{"id":42,"name":"Test Comic","count_of_issues":12,"publisher":{"name":"Publisher"}}}`, "42", "comic"},
		{"MANGA_BAKA", `{"data":[{"id":42,"type":"manga","titles":[{"title":"Test Manga","language":"en","is_primary":true}]}]}`,
			`{"data":{"id":42,"type":"manga","titles":[{"title":"Test Manga","language":"en","is_primary":true}],"status":"completed","tags_v2":[{"name":"Action","is_genre":true},{"name":"School","is_genre":false}]}}`, "42", "comic"},
	}
	for _, fixture := range fixtures {
		t.Run(fixture.name, func(t *testing.T) {
			p, calls := apiFixture(t, fixture.name, fixture.search, fixture.detail)
			hits, err := p.Search(context.Background(), "Test", fixture.media)
			if err != nil || len(hits) != 1 || hits[0].ID != fixture.id {
				t.Fatalf("search: %+v %v", hits, err)
			}
			item, err := p.Get(context.Background(), fixture.id)
			if err != nil || item.ID != fixture.id || item.Media != fixture.media {
				t.Fatalf("get: %+v %v", item, err)
			}
			filterMetadata(&item, p.option)
			if item.Fields["title"] == nil || len(*calls) != 2 {
				t.Fatalf("missing title/calls: %+v", item)
			}
			if fixture.name == "ANILIST" && strings.Join(item.Fields["tags"].([]string), ",") != "high" {
				t.Fatal("AniList rank filter not applied")
			}
			if fixture.name == "MANGADEX" && strings.Join(item.Fields["tags"].([]string), ",") != "School" {
				t.Fatal("MangaDex accepted non-theme tags")
			}
			if fixture.name == "MAL" && (*calls)[0].Header.Get("X-MAL-CLIENT-ID") != "private-key" {
				t.Fatal("missing MAL client id")
			}
		})
	}
}

type fakeProvider struct {
	name  string
	calls *[]string
	found string
	fail  bool
}

func (p fakeProvider) Name() string { return p.name }
func (p fakeProvider) Search(_ context.Context, q, media string) ([]Metadata, error) {
	*p.calls = append(*p.calls, p.name+":"+q)
	if p.fail {
		return nil, errors.New("failed")
	}
	if q != p.found {
		return nil, nil
	}
	return []Metadata{{Provider: p.name, ID: "42", Media: media, Titles: []Title{{Name: q}}, Fields: map[string]any{}}}, nil
}
func (p fakeProvider) Get(_ context.Context, id string) (Metadata, error) {
	return Metadata{Provider: p.name, ID: id, Media: "comic", Titles: []Title{{Name: p.found}}, Fields: map[string]any{"summary": "text"}}, nil
}

func TestProviderOuterOrderAndFailureIsolation(t *testing.T) {
	calls := []string{}
	registry := []registered{
		{provider: fakeProvider{"A", &calls, "", true}},
		{provider: fakeProvider{"B", &calls, "second", false}},
		{provider: fakeProvider{"C", &calls, "first", false}},
	}
	result := matchRegistered(context.Background(), registry, []string{"first", "second", "first"}, "comic")
	if result.Match == nil || result.Match.Provider != "B" || strings.Join(calls, ",") != "A:first,A:second,B:first,B:second" || len(result.Errors) != 2 {
		t.Fatalf("order: %+v %v", result, calls)
	}
}

func TestReferenceMatchingAndFieldFilter(t *testing.T) {
	for _, row := range []struct {
		q, candidate string
		match        bool
	}{
		{"Nar", "Nart", false}, {"Berserk", "Berserku", true}, {"海贼王", "海贼王", true}, {"海贼王", "海贼", false},
		{"Test", "Toast", false}, {"One Piece", "ONE PIECE", true},
	} {
		if matches(row.q, []Title{{Name: row.candidate}}, "") != row.match {
			t.Fatalf("matcher: %+v", row)
		}
	}
	item := Metadata{Provider: "ANILIST", Titles: []Title{{Name: "Main"}, {Name: "标题", Language: "zh"}, {Name: "Main"}},
		Fields: map[string]any{"summary": "<p>Hello</p><script>danger</script>", "tags": []string{"a", "a", ""}, "publisher": ""}}
	filterMetadata(&item, Options{TitleLanguage: "zh", Fields: map[string]bool{"summary": false}})
	if item.Fields["title"] != "标题" || item.Fields["summary"] != nil || item.Fields["publisher"] != nil || len(item.Titles) != 2 {
		t.Fatalf("filter: %+v", item)
	}
	if plain("<p>Hello</p><script>danger</script>") != "Hello" {
		t.Fatal("unsafe summary")
	}
}

func TestRegistryAndHTTPFailures(t *testing.T) {
	c := Config{Providers: []Options{{Name: "MAL", Enabled: true, Priority: 20}, {Name: "MANGADEX", Enabled: true, Priority: 10}, {Name: "MANGA_UPDATES", Enabled: true, Priority: 10}}}
	r, err := c.registry()
	if err != nil || r[0].provider.Name() != "MANGA_UPDATES" || r[1].provider.Name() != "MANGADEX" {
		t.Fatalf("priority: %v %v", r, err)
	}
	c.Providers = append(c.Providers, c.Providers[0])
	if _, err = c.registry(); err == nil {
		t.Fatal("duplicate accepted")
	}
	p, _ := apiFixture(t, "ANILIST", `{"errors":[{"message":"credential secret"}]}`)
	if _, err = p.Search(context.Background(), "test", "comic"); err == nil || strings.Contains(err.Error(), "secret") {
		t.Fatal("API error not sanitized")
	}
	p.client = &http.Client{Transport: roundTrip(func(r *http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: 429, Body: io.NopCloser(strings.NewReader("secret")), Header: http.Header{}}, nil
	})}
	if _, err = p.Search(context.Background(), "test", "comic"); err == nil || err.Error() != "HTTP 429" {
		t.Fatalf("rate error: %v", err)
	}
}

func TestMetadataRoundtrip(t *testing.T) {
	item := Metadata{Provider: "MAL", ID: "42", Fields: map[string]any{"title": "中文"}}
	raw, err := json.Marshal(item)
	if err != nil || !json.Valid(raw) {
		t.Fatal(err)
	}
}
