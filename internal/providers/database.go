package providers

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"net/url"
	"os"
	"path/filepath"
	"strings"

	_ "modernc.org/sqlite"
)

func (p *remoteProvider) openDatabase() (*sql.DB, error) {
	if p.option.Database == "" {
		return nil, errors.New("requires a local provider SQLite database")
	}
	path, err := filepath.Abs(p.option.Database)
	if err != nil {
		return nil, errors.New("invalid database path")
	}
	if _, err := os.Stat(path); err != nil {
		return nil, errors.New("provider database is missing or inaccessible")
	}
	path = filepath.ToSlash(path)
	if !strings.HasPrefix(path, "/") {
		path = "/" + path
	}
	address := url.URL{Scheme: "file", Path: path, RawQuery: "mode=ro"}
	db, err := sql.Open("sqlite", address.String())
	if err != nil {
		return nil, errors.New("cannot open provider database")
	}
	db.SetMaxOpenConns(1)
	return db, nil
}

func readRows(ctx context.Context, db *sql.DB, statement string, args ...any) ([]object, error) {
	rows, err := db.QueryContext(ctx, statement, args...)
	if err != nil {
		return nil, errors.New("provider database schema or query is incompatible")
	}
	defer rows.Close()
	columns, err := rows.Columns()
	if err != nil {
		return nil, err
	}
	result := []object{}
	for rows.Next() {
		values, pointers := make([]any, len(columns)), make([]any, len(columns))
		for i := range values {
			pointers[i] = &values[i]
		}
		if err := rows.Scan(pointers...); err != nil {
			return nil, err
		}
		row := object{}
		for i, column := range columns {
			value := values[i]
			switch v := value.(type) {
			case int64:
				encoded, _ := json.Marshal(v)
				value = json.Number(string(encoded))
			case []byte:
				value = string(v)
			}
			if raw, ok := value.(string); ok && (strings.HasPrefix(raw, "[") || strings.HasPrefix(raw, "{")) {
				decoder := json.NewDecoder(strings.NewReader(raw))
				decoder.UseNumber()
				var decoded any
				if decoder.Decode(&decoded) == nil {
					value = decoded
				}
			}
			row[column] = value
		}
		result = append(result, row)
		if len(result) > 100000 {
			return nil, errors.New("provider database result exceeds safety limit")
		}
	}
	return result, rows.Err()
}

func (p *remoteProvider) databaseSearch(ctx context.Context, query, media string) ([]Metadata, error) {
	db, err := p.openDatabase()
	if err != nil {
		return nil, err
	}
	defer db.Close()
	phrase := `"` + strings.ReplaceAll(query, `"`, `""`) + `"`
	var records []object
	switch p.Name() {
	case "BOOK_WALKER":
		statement := `SELECT id FROM series_fts WHERE (title MATCH ? OR alt_titles MATCH ?)`
		args := []any{phrase, phrase}
		if media == "book" {
			statement += " AND type IN (2,4)"
		} else if media == "comic" {
			statement += " AND type IN (1,3)"
		}
		records, err = readRows(ctx, db, statement+" ORDER BY rank LIMIT 10", args...)
	case "MANGA_BAKA":
		statement := "SELECT id FROM titles_fts WHERE title MATCH ?"
		if media == "book" {
			statement += " AND type = 'novel'"
		} else if media == "comic" {
			statement += " AND type != 'novel'"
		}
		records, err = readRows(ctx, db, statement+" ORDER BY rank LIMIT 20", phrase)
	default:
		return nil, errors.New("database search not supported for this provider")
	}
	if err != nil {
		return nil, err
	}
	result, seen := []Metadata{}, map[string]bool{}
	for _, record := range records {
		id := text(record["id"])
		if seen[id] {
			continue
		}
		seen[id] = true
		item, err := p.readDatabaseItem(ctx, db, id)
		if err != nil {
			return nil, err
		}
		if mediaAllowed(media, item.Media) {
			result = append(result, item)
		}
	}
	return result, nil
}

func (p *remoteProvider) databaseGet(ctx context.Context, id string) (Metadata, error) {
	db, err := p.openDatabase()
	if err != nil {
		return Metadata{}, err
	}
	defer db.Close()
	return p.readDatabaseItem(ctx, db, id)
}

func (p *remoteProvider) readDatabaseItem(ctx context.Context, db *sql.DB, id string) (Metadata, error) {
	rows, err := readRows(ctx, db, "SELECT * FROM series WHERE id=? LIMIT 1", id)
	if err != nil {
		return Metadata{}, err
	}
	if len(rows) == 0 {
		return Metadata{}, errors.New("provider database entry not found")
	}
	if p.Name() == "MANGA_BAKA" {
		return p.mapAPI(rows[0]), nil
	}
	row := rows[0]
	item := newMetadata(p.Name(), id, "comic")
	item.Raw = row
	// Use the actual DB enum values, not the reference mapper's known off-by-one.
	if kind := number(row["type"]); kind == 2 || kind == 4 {
		item.Media = "book"
	}
	title(&item, text(row["title"]), "en")
	for _, name := range stringsIn(row["alt_titles"]) {
		title(&item, name, "")
	}
	item.Fields["summary"] = row["description"]
	tags, err := readRows(ctx, db, `SELECT t.name FROM series_tags st
		LEFT JOIN tags t ON t.id=st.tag_id WHERE st.series_id=?`, id)
	if err != nil {
		return Metadata{}, err
	}
	names := []string{}
	for _, tag := range tags {
		names = append(names, text(tag["name"]))
	}
	item.Fields["tags"] = names
	source(&item, "BookWalker", "https://bookwalker.com/series/"+url.PathEscape(id))
	return item, nil
}
