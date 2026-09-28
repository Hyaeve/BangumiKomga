package providers

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
)

type object = map[string]any

type remoteProvider struct {
	option Options
	client *http.Client
	// Fixed production URLs; tests replace transport, not user-configurable hosts.
	lastRequest time.Time
}

func (p *remoteProvider) Name() string { return p.option.Name }

func newClient(proxy string) (*http.Client, error) {
	transport := http.DefaultTransport.(*http.Transport).Clone()
	if proxy != "" {
		address, err := url.Parse(proxy)
		if err != nil || address.Host == "" || (address.Scheme != "http" && address.Scheme != "https" && address.Scheme != "socks5" && address.Scheme != "socks5h") {
			return nil, errors.New("invalid outbound proxy")
		}
		transport.Proxy = http.ProxyURL(address)
	}
	return &http.Client{Transport: transport, Timeout: 20 * time.Second,
		CheckRedirect: func(request *http.Request, via []*http.Request) error {
			if len(via) >= 5 || request.URL.Scheme != "https" || request.URL.Hostname() != via[0].URL.Hostname() {
				return errors.New("provider redirect rejected")
			}
			return nil
		}}, nil
}

func (p *remoteProvider) request(ctx context.Context, method, address string, body any, headers map[string]string) ([]byte, error) {
	// Bound requests within each match job; never retry authentication or rate-limit failures.
	interval := 350 * time.Millisecond
	if p.Name() == "COMIC_VINE" {
		interval = time.Second
	}
	if delay := interval - time.Since(p.lastRequest); delay > 0 {
		timer := time.NewTimer(delay)
		defer timer.Stop()
		select {
		case <-timer.C:
		case <-ctx.Done():
			return nil, ctx.Err()
		}
	}
	p.lastRequest = time.Now()
	var input io.Reader
	if body != nil {
		encoded, err := json.Marshal(body)
		if err != nil {
			return nil, err
		}
		input = bytes.NewReader(encoded)
	}
	request, err := http.NewRequestWithContext(ctx, method, address, input)
	if err != nil {
		return nil, errors.New("invalid provider request")
	}
	request.Header.Set("User-Agent", "BangumiKomga/1 (https://github.com/Hyaeve/BangumiKomga)")
	request.Header.Set("Accept", "application/json,text/html")
	if body != nil {
		request.Header.Set("Content-Type", "application/json")
	}
	for key, value := range headers {
		request.Header.Set(key, value)
	}
	response, err := p.client.Do(request)
	if err != nil {
		// Do not expose URLs carrying API keys or proxy credentials.
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		return nil, errors.New("provider network request failed")
	}
	defer response.Body.Close()
	if response.StatusCode != 200 {
		return nil, fmt.Errorf("HTTP %d", response.StatusCode)
	}
	data, err := io.ReadAll(io.LimitReader(response.Body, 8*1024*1024+1))
	if err != nil || len(data) > 8*1024*1024 {
		return nil, errors.New("invalid or oversized provider response")
	}
	return data, nil
}

func (p *remoteProvider) json(ctx context.Context, method, address string, body any, headers map[string]string) (object, error) {
	raw, err := p.request(ctx, method, address, body, headers)
	if err != nil {
		return nil, err
	}
	var data object
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	if err := decoder.Decode(&data); err != nil || data == nil {
		return nil, errors.New("invalid provider JSON")
	}
	if len(array(data["errors"])) > 0 {
		return nil, errors.New("provider returned API errors")
	}
	return data, nil
}

func obj(value any) object {
	result, _ := value.(map[string]any)
	if result == nil {
		return object{}
	}
	return result
}
func array(value any) []any { result, _ := value.([]any); return result }
func text(value any) string {
	switch value := value.(type) {
	case string:
		return value
	case json.Number:
		return value.String()
	case float64:
		return strconv.FormatFloat(value, 'f', -1, 64)
	case int:
		return strconv.Itoa(value)
	case int64:
		return strconv.FormatInt(value, 10)
	}
	return ""
}
func number(value any) int {
	var result int
	fmt.Sscan(text(value), &result)
	return result
}
func stringsIn(value any) []string {
	result := []string{}
	for _, item := range array(value) {
		if value := text(item); value != "" {
			result = append(result, value)
		}
	}
	return result
}
func child(data object, keys ...string) any {
	var current any = data
	for _, key := range keys {
		current = obj(current)[key]
	}
	return current
}
func first(values ...string) string {
	for _, value := range values {
		if strings.TrimSpace(value) != "" {
			return value
		}
	}
	return ""
}
func queryURL(base string, params url.Values) string { return base + "?" + params.Encode() }
func newMetadata(provider, id, media string) Metadata {
	return Metadata{Provider: provider, ID: id, Media: media, Fields: map[string]any{}}
}
func title(item *Metadata, name, language string) {
	if strings.TrimSpace(name) != "" {
		item.Titles = append(item.Titles, Title{Name: name, Language: language})
	}
}
func source(item *Metadata, label, address string) {
	item.Fields["links"] = []map[string]string{{"label": label, "url": address}}
}
func addNames(values []any, key string) []string {
	result := []string{}
	for _, value := range values {
		result = append(result, text(obj(value)[key]))
	}
	return unique(result)
}
func mediaKind(kind string) string {
	switch strings.ToLower(kind) {
	case "novel", "light_novel", "light novel", "novel (jp)", "novel (kr)", "novel (cn)":
		return "book"
	case "manga", "one_shot", "oneshot", "one shot", "doujinshi", "manhwa", "manhua", "oel", "comic", "webtoon", "oel manga",
		"artbook", "filipino", "indonesian", "thai", "vietnamese", "malaysian", "nordic", "french", "spanish":
		return "comic"
	}
	return ""
}
func setStatus(item *Metadata, status string) {
	switch strings.ToLower(status) {
	case "finished", "completed", "ended", "finished_publishing", "complete":
		item.Fields["status"] = "ENDED"
	case "releasing", "ongoing", "publishing", "currently_publishing", "not_yet_published", "not_yet_released":
		item.Fields["status"] = "ONGOING"
	case "hiatus", "on_hiatus":
		item.Fields["status"] = "HIATUS"
	case "cancelled", "discontinued", "abandoned":
		item.Fields["status"] = "ABANDONED"
	}
}
func positive(item *Metadata, field string, raw any) {
	if value := number(raw); value > 0 {
		item.Fields[field] = value
	}
}
func publisher(values []any, nameKey string, original bool) string {
	preferred := "English"
	if original {
		preferred = "Original"
	}
	for _, value := range values {
		item := obj(value)
		if text(item["type"]) == preferred && text(item[nameKey]) != "" {
			return text(item[nameKey])
		}
	}
	for _, value := range values {
		item := obj(value)
		if text(item["type"]) == "Original" {
			return text(item[nameKey])
		}
	}
	return ""
}
