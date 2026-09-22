# FitForge

A personal, data-driven workout tracker and daily training protocol. FitForge loads your week from a single JSON file, shows **today’s session** on open, and keeps progress on-device—no accounts, no backend.

**Live app:** [fitforgeweb.vercel.app](https://fitforgeweb.vercel.app)

---

## Features

- **Three training plans** — switch anytime; progress is saved **per plan** and **per day of week** for the current calendar day
- **Day picker** — page load always shows **today’s** session; tap another weekday to run a **catch-up** workout (e.g. on a rest day)
  - **Classic Split** (`schedule`) — body-part split with optional volume and finishers
  - **Enhanced Split** (`schedule_2`) — same weekly layout with extra exercises, core-focused finishers, and deeper anatomy notes
  - **V-Tapper** (`schedule_3`) — push/pull/legs + V-taper emphasis, mid-week rest, optional cardio day
- **Set tracking** — tap set bubbles to mark complete; optional exercises in a collapsible section
- **Rest timer** — floating countdown after each set; vibration and optional voice cue when rest ends
- **Workout completion** — progress bar and confetti at 100%
- **Weekly overview** — calendar modal for the active plan
- **Spotify hub** — playlists and podcasts from `data.json`, grouped by type with names and descriptions; open in **iOS**, **Android**, or **Web** (device choice in the top bar, default iOS)
- **Themes** — Flat Dark (default), White Clay, Neo Brutal, Minimal
- **PWA** — installable via `manifest.json` and `sw.js`; offline-friendly shell with network-first `data.json`

---

## Quick start

FitForge uses `fetch()` to load `data.json`, so open it through a **local HTTP server** (not `file://`).

```bash
cd FitForge
python3 -m http.server 8080
```

Then visit [http://localhost:8080](http://localhost:8080) (main UI is `index.html`).

For PWA/service worker behavior, use the same origin in production (e.g. Vercel).

---

## Project structure

| File | Purpose |
|------|---------|
| `index.html` | Main app — themes, plans, tracking, Spotify, PWA |
| `data.json` | Workout schedules, audio links, exercise metadata |
| `manifest.json` | Web app manifest (name, icons, theme) |
| `sw.js` | Service worker and caching |
| `forge-icon.svg` / `forge-icon-*.png` | Tab & home-screen icons (🔥 on dark tile) |
| `Personality.svg` | Legacy avatar asset |
| `tuner.html` | Standalone speech-voice tuning utility |
| `neo.html`, `minimal.html` | Alternate single-theme prototypes |
| `index.backup.html` | Earlier backup of the main page |

---

## Customizing workouts (`data.json`)

### Audio

```json
"audio": {
  "playlists": [
    {
      "name": "My Playlist",
      "description": "Shown in the Spotify modal",
      "type": "playlist",
      "url": "https://open.spotify.com/playlist/..."
    },
    {
      "name": "My Podcast",
      "description": "Optional blurb",
      "type": "podcast",
      "url": "https://open.spotify.com/show/..."
    }
  ],
  "podcasts": []
}
```

Items in `audio.playlists` with `type: "playlist"` or `type: "podcast"` appear under the matching category in the UI. Legacy entries in `audio.podcasts` are merged in if they are not duplicates.

### Schedules

Three top-level arrays define the plans:

- `schedule` — Classic Split  
- `schedule_2` — Enhanced Split  
- `schedule_3` — V-Tapper  

Each is an array of **7 day objects** (`Sunday` … `Saturday`):

| Field | Description |
|-------|-------------|
| `day_of_week` | e.g. `"Monday"` |
| `focus` | Headline for that day |
| `is_rest_day` | `true` for recovery / rest (no set tracking) |
| `notes` | Shown on rest days |
| `exercises` | Main lifts (see below) |
| `optional_exercises` | Optional list (same shape as exercises) |
| `finisher` | Optional burnout block (name, sets/reps or `duration_minutes`, `machine_alternative`, optional `anatomy_pov`) |

**Exercise object:**

| Field | Description |
|-------|-------------|
| `name` | Display name |
| `sets` | Number of set bubbles |
| `reps` | e.g. `"8-12"` or `"10 per leg"` |
| `rest_seconds` | Rest timer duration after completing a set |
| `anatomy_pov` | “Science” expandable copy |
| `machine_alternative` | Substitution hint |

After editing `data.json`, refresh the app. The service worker prefers the network for `data.json`; bump `CACHE_NAME` in `sw.js` if cached assets stick on an install.

---

## Local storage keys

| Key | Stores |
|-----|--------|
| `fitforge_plan` | Active plan key: `schedule`, `schedule_2`, or `schedule_3` |
| `fitforge_theme` | `flat`, `clay`, `brutal`, or `minimal` |
| `fitforge_device` | Spotify target: `ios`, `android`, or `web` |
| `fitforge_state` | Daily progress (date, voice toggle, per-plan checked sets and finisher) |

Progress resets when the calendar date changes.

---

## Deploy

Static hosting is enough. Example: connect the repo to [Vercel](https://vercel.com) with no build step; set the project root to this folder and ensure `index.html` is the entry.

Update `start_url` in `manifest.json` if your production URL differs.

---

## Credits

Designed by **[itsmeramc](https://bikkina.vercel.app)**.

License: personal project—fork and adapt for your own protocol; no warranty on training advice. Consult a professional before starting any program.
