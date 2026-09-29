package providers

import (
	"context"
	"testing"
)

func TestManualSearchRejectsInvalidInput(t *testing.T) {
	for _, input := range []struct{ query, media string }{{"", "comic"}, {"Title", "invalid"}} {
		if _, err := Search(context.Background(), Config{}, "MANGADEX", input.query, input.media); err == nil {
			t.Fatal("invalid manual search accepted")
		}
	}
	if _, err := Search(context.Background(), Config{}, "MANGADEX", "Title", "comic"); err == nil {
		t.Fatal("unconfigured provider accepted")
	}
}
