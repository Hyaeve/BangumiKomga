package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"strings"
	"time"

	"github.com/Hyaeve/BangumiKomga/internal/coreprotocol"
)

func run(input io.Reader, output io.Writer) error {
	raw, err := io.ReadAll(io.LimitReader(input, 65537))
	if err != nil {
		return err
	}
	if len(raw) > 65536 {
		return fmt.Errorf("request exceeds 64 KiB")
	}
	var request coreprotocol.Request
	if err := json.Unmarshal(raw, &request); err != nil {
		return fmt.Errorf("invalid request JSON: %w", err)
	}
	timeout := 20 * time.Second
	if strings.HasPrefix(request.Action, "providers.") {
		timeout = 180 * time.Second
	}
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	return json.NewEncoder(output).Encode(coreprotocol.Handle(ctx, request))
}

func main() {
	if err := run(os.Stdin, os.Stdout); err != nil {
		json.NewEncoder(os.Stdout).Encode(coreprotocol.Response{Protocol: coreprotocol.Version, Error: err.Error()})
		os.Exit(1)
	}
}
