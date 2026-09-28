package providers

import (
	"bytes"
	"image"
	"image/color"
	"image/png"
	"testing"
)

func TestReferenceAverageHash(t *testing.T) {
	img := image.NewRGBA(image.Rect(0, 0, 64, 64))
	for y := 0; y < 64; y++ {
		for x := 0; x < 64; x++ {
			if x < 32 {
				img.Set(x, y, color.White)
			} else {
				img.Set(x, y, color.Black)
			}
		}
	}
	var output bytes.Buffer
	if err := png.Encode(&output, img); err != nil {
		t.Fatal(err)
	}
	hash, err := averageHash(output.Bytes())
	if err != nil || len(hash) != 1024 {
		t.Fatal(err)
	}
	for y := 0; y < 32; y++ {
		for x := 0; x < 32; x++ {
			if hash[y*32+x] != (x < 16) {
				t.Fatal("reference box hash mismatch")
			}
		}
	}
	if _, err := averageHash([]byte("not image")); err == nil {
		t.Fatal("invalid image accepted")
	}
}
