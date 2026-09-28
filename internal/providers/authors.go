package providers

import "strings"

func (p *remoteProvider) roles(artist bool) []string {
	if artist {
		if p.option.ArtistRoles != nil {
			return p.option.ArtistRoles
		}
		return []string{"penciller", "inker", "colorist", "letterer", "cover"}
	}
	if p.option.AuthorRoles != nil {
		return p.option.AuthorRoles
	}
	return []string{"writer"}
}

func (p *remoteProvider) authors(data object) []map[string]string {
	out := []map[string]string{}
	add := func(name string, roles []string) {
		if strings.TrimSpace(name) == "" {
			return
		}
		for _, role := range roles {
			out = append(out, map[string]string{"name": strings.TrimSpace(name), "role": role})
		}
	}
	switch p.Name() {
	case "MANGA_UPDATES":
		for _, value := range array(data["authors"]) {
			a := obj(value)
			add(text(a["name"]), p.roles(text(a["type"]) != "Author"))
		}
	case "ANILIST", "MAL":
		rows := array(data["authors"])
		if p.Name() == "ANILIST" {
			rows = array(child(data, "staff", "edges"))
		}
		for _, value := range rows {
			a := obj(value)
			role := text(a["role"])
			name := strings.TrimSpace(text(child(a, "node", "first_name")) + " " + text(child(a, "node", "last_name")))
			if p.Name() == "ANILIST" {
				name = first(text(child(a, "node", "name", "userPreferred")), text(child(a, "node", "name", "full")))
				role = strings.TrimSpace(vizParentheses.ReplaceAllString(role, ""))
			}
			switch role {
			case "Story & Art":
				add(name, p.roles(true))
				add(name, p.roles(false))
			case "Story":
				add(name, p.roles(false))
			case "Art":
				add(name, p.roles(true))
			case "Original Story", "Original Creator":
				if p.Name() == "ANILIST" {
					add(name, p.roles(false))
				}
			case "Illustration":
				if p.Name() == "ANILIST" {
					add(name, p.roles(true))
				}
			}
		}
	case "MANGADEX":
		for _, value := range array(data["relationships"]) {
			r := obj(value)
			if text(r["type"]) == "author" || text(r["type"]) == "artist" {
				add(text(child(r, "attributes", "name")), p.roles(text(r["type"]) == "artist"))
			}
		}
	}
	return out
}
