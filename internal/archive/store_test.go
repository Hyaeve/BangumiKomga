package archive

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"testing"
)

func fixture(t *testing.T) string {
	t.Helper()
	folder := t.TempDir()
	db, err := sql.Open("sqlite", filepath.Join(folder, "bangumi.sqlite3"))
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	_, err = db.Exec(`
		CREATE TABLE state(key TEXT PRIMARY KEY,value TEXT);
		INSERT INTO state VALUES ('version','1');
		CREATE TABLE subjects(id INTEGER PRIMARY KEY,payload TEXT);
		CREATE TABLE names(name TEXT,subject_id INTEGER);
		CREATE INDEX names_exact ON names(name);
		CREATE VIRTUAL TABLE names_fts USING fts5(name,subject_id UNINDEXED, tokenize='trigram');
		CREATE TABLE relations(subject_id INTEGER,related_subject_id INTEGER,relation_type INTEGER);
		INSERT INTO subjects VALUES (1,'{"id":1,"name":"万古之王","summary":"原文","series":true}');
		INSERT INTO subjects VALUES (2,'{"id":2,"name":"第一卷","series":false}');
		INSERT INTO relations VALUES (1,2,1003);`)
	if err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"万古之王", "the ancient king", "100%", `a"b`} {
		if _, err := db.Exec("INSERT INTO names VALUES (?,1)", name); err != nil {
			t.Fatal(err)
		}
		if _, err := db.Exec("INSERT INTO names_fts VALUES (?,1)", name); err != nil {
			t.Fatal(err)
		}
	}
	return folder
}

func TestReadQueries(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, fixture(t))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	for _, query := range []string{"万古之王", "万古", "ancient", "%", `a"b`} {
		results, err := store.Search(ctx, query)
		if err != nil || len(results) != 1 {
			t.Fatalf("search %q: %s, %v", query, results, err)
		}
	}
	for _, query := range []string{"", "unknown", "' OR 1=1 --", "_"} {
		results, err := store.Search(ctx, query)
		if err != nil || len(results) != 0 {
			t.Fatalf("search %q: %s, %v", query, results, err)
		}
	}
	detail, err := store.Get(ctx, 1)
	if err != nil || !json.Valid(detail) {
		t.Fatalf("detail: %s %v", detail, err)
	}
	missing, err := store.Get(ctx, 999)
	if err != nil || string(missing) != "{}" {
		t.Fatalf("missing: %s %v", missing, err)
	}
	relations, err := store.Relations(ctx, 1)
	if err != nil || len(relations) != 1 {
		t.Fatalf("relations: %s %v", relations, err)
	}
	var relation map[string]any
	json.Unmarshal(relations[0], &relation)
	if relation["relation"] != float64(1003) || relation["id"] != float64(2) {
		t.Fatalf("relation: %v", relation)
	}
	if _, err := store.db.Exec("DELETE FROM subjects"); err == nil {
		t.Fatal("archive must be read-only")
	}
}

func TestBoundedAndCancelled(t *testing.T) {
	folder := fixture(t)
	db, err := sql.Open("sqlite", filepath.Join(folder, "bangumi.sqlite3"))
	if err != nil {
		t.Fatal(err)
	}
	for i := 3; i < 220; i++ {
		payload := fmt.Sprintf(`{"id":%d,"name":"test"}`, i)
		if _, err := db.Exec("INSERT INTO subjects VALUES (?,?)", i, payload); err != nil {
			t.Fatal(err)
		}
		db.Exec("INSERT INTO names VALUES ('test',?)", i)
		db.Exec("INSERT INTO names_fts VALUES ('test',?)", i)
	}
	db.Close()
	store, err := Open(context.Background(), folder)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	results, err := store.Search(context.Background(), "test")
	if err != nil || len(results) != MaxResults {
		t.Fatalf("bounded search: %d %v", len(results), err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := store.Get(ctx, 1); err == nil {
		t.Fatal("cancelled request was accepted")
	}
}

func TestMissingAndInvalidIndex(t *testing.T) {
	folder := t.TempDir()
	if _, err := Open(context.Background(), folder); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("missing index: %v", err)
	}
	if _, err := os.Stat(filepath.Join(folder, "bangumi.sqlite3")); !errors.Is(err, os.ErrNotExist) {
		t.Fatal("read created a database")
	}
	folder = fixture(t)
	db, _ := sql.Open("sqlite", filepath.Join(folder, "bangumi.sqlite3"))
	db.Exec("UPDATE state SET value='99'")
	db.Close()
	if _, err := Open(context.Background(), folder); err == nil {
		t.Fatal("unsupported schema accepted")
	}
}
