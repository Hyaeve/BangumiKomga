package providers

import (
	"context"
	"testing"
)

func TestMangaDexBookUsesOriginalCover(t *testing.T) {
	p, _ := apiFixture(t, "MANGADEX", `{}`)
	item, err := p.book(context.Background(), "series", "cover.jpg")
	if err != nil || item.Cover != "https://uploads.mangadex.org/covers/series/cover.jpg" {
		t.Fatalf("original cover expected: %+v %v", item, err)
	}
}

func TestComicVineCoverResolutionOrder(t *testing.T) {
	sizes := []string{"original_url", "super_url", "medium_url", "small_url", "thumb_url", "tiny_url", "icon_url"}
	image := map[string]any{}
	for _, size := range sizes {
		image[size] = "https://example.com/" + size
	}
	data := map[string]any{"image": image}
	for _, size := range sizes {
		if got := comicVineCover(data); got != image[size] {
			t.Fatalf("%s expected, got %s", size, got)
		}
		delete(image, size)
	}
	if comicVineCover(data) != "" {
		t.Fatal("missing cover must remain empty")
	}
}

func TestComicVineBookUsesOriginalCover(t *testing.T) {
	p, _ := apiFixture(t, "COMIC_VINE", `{"status_code":1,"results":{"id":3,"volume":{"id":1},"image":{"original_url":"https://example.com/original.jpg","medium_url":"https://example.com/medium.jpg","small_url":"https://example.com/small.jpg"}}}`)
	item, err := p.book(context.Background(), "1", "3")
	if err != nil || item.Cover != "https://example.com/original.jpg" {
		t.Fatalf("original cover expected: %+v %v", item, err)
	}
}
