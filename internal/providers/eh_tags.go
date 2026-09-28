package providers

import "strings"

// Default fallback lists from komf-rs providers/ehentai.rs.
var ehBlacklistedTags = strings.Fields("extraneous_ads already_uploaded missing_cover forbidden_content replaced compilation incomplete caption")
var ehMaleOnlyTags = strings.Split("dilf|old man|feminization|giant|miniguy|tall man|gyaru-oh|bbm|ssbbm|dickgirl on male|no balls|cuntboy|pegging|alien|bat boy|bear boy|bee boy|bird boy|bunny boy|catboy|cowman|deer boy|demon|dog boy|elephant boy|fox boy|frog boy|giraffe boy|hedgehog boy|hippo boy|horse boy|hyena boy|insect boy|kangaroo boy|lizard guy|merman|minotaur|monkey boy|monster|moth boy|mouse boy|mushroom boy|otter boy|panda boy|pig man|plant boy|raccoon boy|rhinoceros boy|shark boy|sheep boy|skunk boy|slime boy|snake boy|spider boy|squid boy|squirrel boy|wolf boy|bull|lion|clothed female nude male|mecha boy|ninja|policeman|priest|steward|mmm threesome|josou seme|otokofutanari|yaoi|males only|pussyboys only|sole male|sole pussyboy|tomgirl|virginity|widower|brother|father|grandfather|uncle|low shotacon", "|")

func contains(values []string, wanted string) bool {
	for _, value := range values {
		if value == wanted {
			return true
		}
	}
	return false
}

func filterEHTags(raw []string) []string {
	result := []string{}
	for _, tag := range raw {
		namespace, value, ok := strings.Cut(tag, ":")
		if !ok || strings.TrimSpace(value) == "" {
			continue
		}
		lower := strings.ToLower(strings.TrimSpace(value))
		switch strings.ToLower(namespace) {
		case "female", "mixed", "location":
			result = append(result, value)
		case "parody":
			if lower != "original" && lower != "various" {
				result = append(result, "parody:"+value)
			}
		case "character":
			result = append(result, "character:"+value)
		case "male":
			if contains(ehMaleOnlyTags, lower) {
				result = append(result, value)
			}
		case "other", "tag":
			if !contains(ehBlacklistedTags, strings.ReplaceAll(lower, " ", "_")) {
				result = append(result, value)
			}
		}
	}
	return unique(result)
}
