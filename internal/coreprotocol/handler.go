// Package coreprotocol defines the versioned, local JSON boundary used during
// backend migration. No HTTP port or external service is required.
package coreprotocol

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"

	"github.com/Hyaeve/BangumiKomga/internal/archive"
	"github.com/Hyaeve/BangumiKomga/internal/providers"
)

const Version = 1

type Request struct {
	Protocol       int                    `json:"protocol"`
	Action         string                 `json:"action"`
	Folder         string                 `json:"folder"`
	Query          string                 `json:"query"`
	ID             int64                  `json:"id"`
	ProviderConfig providers.Config       `json:"provider_config"`
	Queries        []string               `json:"queries"`
	Media          string                 `json:"media_type"`
	Provider       string                 `json:"provider"`
	ProviderID     string                 `json:"provider_id"`
	MatchContext   providers.MatchContext `json:"match_context"`
	BookID         string                 `json:"book_id"`
	LocalBooks     []providers.LocalBook  `json:"local_books"`
}

type Response struct {
	Protocol int    `json:"protocol"`
	Data     any    `json:"data,omitempty"`
	Error    string `json:"error,omitempty"`
}

func Handle(ctx context.Context, request Request) Response {
	data, err := execute(ctx, request)
	if err != nil {
		return Response{Protocol: Version, Error: err.Error()}
	}
	return Response{Protocol: Version, Data: data}
}

func execute(ctx context.Context, request Request) (any, error) {
	if request.Protocol != Version {
		return nil, fmt.Errorf("unsupported protocol %d", request.Protocol)
	}
	if request.Action == "capabilities" {
		return map[string]any{
			"archive_schema": archive.SchemaVersion,
			"actions":        []string{"archive.search", "archive.get", "archive.relations", "providers.catalog", "providers.search", "providers.match", "providers.get", "providers.books", "providers.book", "providers.associate"},
		}, nil
	}
	switch request.Action {
	case "providers.search":
		return providers.Search(ctx, request.ProviderConfig, request.Provider, request.Query, request.Media)
	case "providers.catalog":
		return providers.Catalog(), nil
	case "providers.match":
		if len(request.Queries) > 20 {
			return nil, errors.New("too many title candidates")
		}
		return providers.MatchWithContext(ctx, request.ProviderConfig, request.Queries, request.Media, request.MatchContext)
	case "providers.get":
		return providers.Get(ctx, request.ProviderConfig, request.Provider, request.ProviderID)
	case "providers.books":
		return providers.Books(ctx, request.ProviderConfig, request.Provider, request.ProviderID)
	case "providers.book":
		return providers.Book(ctx, request.ProviderConfig, request.Provider, request.ProviderID, request.BookID)
	case "providers.associate":
		books, err := providers.Books(ctx, request.ProviderConfig, request.Provider, request.ProviderID)
		if err != nil {
			return nil, err
		}
		return providers.Associate(request.LocalBooks, books, request.Media), nil
	}
	switch request.Action {
	case "archive.search", "archive.get", "archive.relations":
	default:
		return nil, fmt.Errorf("unsupported action %q", request.Action)
	}
	if request.Folder == "" {
		return nil, errors.New("archive folder is required")
	}
	if request.Action != "archive.search" && request.ID <= 0 {
		return nil, errors.New("subject id must be positive")
	}
	store, err := archive.Open(ctx, request.Folder)
	if errors.Is(err, os.ErrNotExist) {
		if request.Action == "archive.get" {
			return json.RawMessage(`{}`), nil
		}
		return []json.RawMessage{}, nil
	}
	if err != nil {
		return nil, err
	}
	defer store.Close()
	switch request.Action {
	case "archive.search":
		return store.Search(ctx, request.Query)
	case "archive.get":
		return store.Get(ctx, request.ID)
	default:
		return store.Relations(ctx, request.ID)
	}
}
