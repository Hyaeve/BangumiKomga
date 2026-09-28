// Package archive reads the shared Bangumi SQLite index without modifying it.
package archive

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"strings"

	_ "modernc.org/sqlite"
)

const SchemaVersion = "1"
const MaxResults = 200

type Store struct {
	db *sql.DB
}

func Open(ctx context.Context, folder string) (*Store, error) {
	path, err := filepath.Abs(filepath.Join(folder, "bangumi.sqlite3"))
	if err != nil {
		return nil, err
	}
	// A read-only missing index is different from an invalid/corrupt index.
	if _, err = os.Stat(path); err != nil {
		return nil, err
	}
	path = filepath.ToSlash(path)
	if !strings.HasPrefix(path, "/") {
		path = "/" + path
	}
	uri := url.URL{Scheme: "file", Path: path, RawQuery: "mode=ro"}
	db, err := sql.Open("sqlite", uri.String())
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(1)
	var version string
	err = db.QueryRowContext(ctx, "SELECT value FROM state WHERE key='version'").Scan(&version)
	if err != nil || version != SchemaVersion {
		db.Close()
		if err != nil {
			return nil, fmt.Errorf("read archive schema: %w", err)
		}
		return nil, fmt.Errorf("unsupported archive schema %q", version)
	}
	return &Store{db: db}, nil
}

func (s *Store) Close() error { return s.db.Close() }

func (s *Store) Get(ctx context.Context, id int64) (json.RawMessage, error) {
	var payload string
	err := s.db.QueryRowContext(ctx, "SELECT payload FROM subjects WHERE id=?", id).Scan(&payload)
	if errors.Is(err, sql.ErrNoRows) {
		return json.RawMessage(`{}`), nil
	}
	if err != nil {
		return nil, err
	}
	if !json.Valid([]byte(payload)) {
		return nil, errors.New("invalid subject JSON in archive")
	}
	return json.RawMessage(payload), nil
}

// Search accepts a canonical name (the bridge applies the existing zh-cn
// conversion and Unicode case folding before crossing the language boundary).
func (s *Store) Search(ctx context.Context, query string) ([]json.RawMessage, error) {
	query = strings.TrimSpace(query)
	result := make([]json.RawMessage, 0)
	if query == "" {
		return result, nil
	}
	ids := make([]int64, 0, MaxResults)
	seen := make(map[int64]bool)
	collect := func(statement string, arg string) error {
		rows, err := s.db.QueryContext(ctx, statement, arg, MaxResults)
		if err != nil {
			return err
		}
		defer rows.Close()
		for rows.Next() {
			var id int64
			if err := rows.Scan(&id); err != nil {
				return err
			}
			if !seen[id] && len(ids) < MaxResults {
				seen[id] = true
				ids = append(ids, id)
			}
		}
		return rows.Err()
	}
	if err := collect("SELECT DISTINCT subject_id FROM names WHERE name=? LIMIT ?", query); err != nil {
		return nil, err
	}
	if len([]rune(query)) >= 3 {
		expression := `"` + strings.ReplaceAll(query, `"`, `""`) + `"`
		if err := collect("SELECT DISTINCT subject_id FROM names_fts WHERE names_fts MATCH ? LIMIT ?", expression); err != nil {
			return nil, err
		}
	} else {
		escaped := strings.NewReplacer(`\`, `\\`, `%`, `\%`, `_`, `\_`).Replace(query)
		if err := collect(`SELECT DISTINCT subject_id FROM names WHERE name LIKE ? ESCAPE '\' LIMIT ?`, "%"+escaped+"%"); err != nil {
			return nil, err
		}
	}
	if len(ids) == 0 {
		return result, nil
	}
	args := make([]any, len(ids))
	marks := make([]string, len(ids))
	for i, id := range ids {
		args[i], marks[i] = id, "?"
	}
	rows, err := s.db.QueryContext(ctx,
		"SELECT payload FROM subjects WHERE id IN ("+strings.Join(marks, ",")+") ORDER BY id", args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var payload string
		if err := rows.Scan(&payload); err != nil {
			return nil, err
		}
		if !json.Valid([]byte(payload)) {
			return nil, errors.New("invalid subject JSON in archive")
		}
		result = append(result, json.RawMessage(payload))
	}
	return result, rows.Err()
}

func (s *Store) Relations(ctx context.Context, id int64) ([]json.RawMessage, error) {
	result := make([]json.RawMessage, 0)
	rows, err := s.db.QueryContext(ctx, `SELECT s.payload,r.relation_type FROM relations r
		JOIN subjects s ON s.id=r.related_subject_id WHERE r.subject_id=?`, id)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var payload string
		var relation int
		if err := rows.Scan(&payload, &relation); err != nil {
			return nil, err
		}
		var item map[string]json.RawMessage
		if err := json.Unmarshal([]byte(payload), &item); err != nil {
			return nil, err
		}
		if item == nil {
			return nil, errors.New("invalid relation JSON in archive")
		}
		item["relation"], _ = json.Marshal(relation)
		encoded, err := json.Marshal(item)
		if err != nil {
			return nil, err
		}
		result = append(result, encoded)
	}
	return result, rows.Err()
}
