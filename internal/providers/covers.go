package providers

// Keep the provider's original image; reduced variants are fallbacks only.
func comicVineCover(data map[string]any) string {
	for _, size := range []string{"original_url", "super_url", "medium_url", "small_url", "thumb_url", "tiny_url", "icon_url"} {
		if address := text(child(data, "image", size)); address != "" {
			return address
		}
	}
	return ""
}
