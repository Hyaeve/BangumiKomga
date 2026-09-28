package coreprotocol

import (
	"context"
	"testing"
)

func TestValidationAndMissingArchive(t *testing.T) {
	ctx := context.Background()
	for _, request := range []Request{
		{Protocol: 99, Action: "capabilities"},
		{Protocol: 1, Action: "unknown"},
		{Protocol: 1, Action: "archive.get", ID: 1},
		{Protocol: 1, Action: "archive.get", Folder: t.TempDir(), ID: -1},
	} {
		if response := Handle(ctx, request); response.Error == "" {
			t.Fatalf("accepted invalid request: %+v", request)
		}
	}
	for _, action := range []string{"archive.search", "archive.get", "archive.relations"} {
		response := Handle(ctx, Request{Protocol: 1, Action: action, Folder: t.TempDir(), ID: 1})
		if response.Error != "" || response.Protocol != 1 || response.Data == nil {
			t.Fatalf("%s: %+v", action, response)
		}
	}
	if response := Handle(ctx, Request{Protocol: 1, Action: "capabilities"}); response.Error != "" {
		t.Fatal(response.Error)
	}
}
