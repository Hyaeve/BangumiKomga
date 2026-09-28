package main

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"
)

func TestProtocolIO(t *testing.T) {
	var output bytes.Buffer
	if err := run(strings.NewReader(`{"protocol":1,"action":"capabilities"}`), &output); err != nil {
		t.Fatal(err)
	}
	if !json.Valid(output.Bytes()) {
		t.Fatalf("invalid response: %s", output.Bytes())
	}
	for _, input := range []string{"{", "{}{}", strings.Repeat(" ", 65537)} {
		if err := run(strings.NewReader(input), &output); err == nil {
			t.Fatal("invalid input accepted")
		}
	}
}
