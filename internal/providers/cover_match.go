package providers

import (
	"bytes"
	"context"
	"errors"
	_ "golang.org/x/image/webp"
	"image"
	_ "image/gif"
	_ "image/jpeg"
	_ "image/png"
	"io"
	"net/url"
	"os"
	"strings"
)

// Reference ComicVine uses 32x32 box-resampled average hash, not a neural
// similarity score. Invalid/oversized images are a non-match.
func averageHash(raw []byte) ([]bool, error) {
	config, _, err := image.DecodeConfig(bytes.NewReader(raw))
	if err != nil || config.Width <= 0 || config.Height <= 0 || int64(config.Width)*int64(config.Height) > 40_000_000 {
		return nil, errors.New("invalid cover image")
	}
	img, _, err := image.Decode(bytes.NewReader(raw))
	if err != nil {
		return nil, errors.New("unsupported cover image")
	}
	bounds := img.Bounds()
	luma, mean := make([]float64, 1024), 0.0
	for y := 0; y < 32; y++ {
		for x := 0; x < 32; x++ {
			x0, y0 := x*config.Width/32, y*config.Height/32
			x1, y1 := min(max((x+1)*config.Width/32, x0+1), config.Width), min(max((y+1)*config.Height/32, y0+1), config.Height)
			var red, green, blue, count uint64
			for sy := y0; sy < y1; sy++ {
				for sx := x0; sx < x1; sx++ {
					r, g, b, _ := img.At(bounds.Min.X+sx, bounds.Min.Y+sy).RGBA()
					red, green, blue, count = red+uint64(r>>8), green+uint64(g>>8), blue+uint64(b>>8), count+1
				}
			}
			value := float64(red/count)*0.299 + float64(green/count)*0.587 + float64(blue/count)*0.114
			luma[y*32+x], mean = value, mean+value/1024
		}
	}
	result := make([]bool, 1024)
	for i, value := range luma {
		result[i] = value >= mean
	}
	return result, nil
}

func (p *remoteProvider) coverMatch(ctx context.Context, candidate Metadata, context MatchContext) (bool, error) {
	if context.CoverPath == "" {
		return false, nil
	}
	qualifier := parseBookRange(context.BookName, "comic")
	if qualifier == nil {
		qualifier = parseBookRange(context.BookName, "book")
	}
	issue := obj(candidate.Raw["first_issue"])
	number := rangeNumber(issue["issue_number"])
	if qualifier == nil || number == nil || number.Start != qualifier.Start {
		return false, nil
	}
	file, err := os.Open(context.CoverPath)
	if err != nil {
		return false, nil
	}
	defer file.Close()
	raw, err := io.ReadAll(io.LimitReader(file, 8*1024*1024+1))
	if err != nil || len(raw) > 8*1024*1024 {
		return false, nil
	}
	local, err := averageHash(raw)
	if err != nil {
		return false, nil
	}
	book, err := p.book(ctx, candidate.ID, text(issue["id"]))
	if err != nil {
		return false, err
	}
	address, err := url.Parse(book.Cover)
	if err != nil || address.Scheme != "https" || address.User != nil ||
		!(address.Hostname() == "gamespot.com" || strings.HasSuffix(address.Hostname(), ".gamespot.com")) {
		return false, nil
	}
	imageBytes, err := p.request(ctx, "GET", book.Cover, nil, nil)
	if err != nil {
		return false, err
	}
	remote, err := averageHash(imageBytes)
	if err != nil {
		return false, nil
	}
	difference := 0
	for i := range local {
		if local[i] != remote[i] {
			difference++
		}
	}
	return float64(difference)/1024 <= 0.1, nil
}
