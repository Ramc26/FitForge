# FitForge

FitForge is a personal workout app with a gym coach named **Hanu**. The phone shows today's session from `data.json`. Sets, body weight, and Hanu's memory live in Google Sheets. The interface is a mobile-first PWA aimed at someone standing between sets.

## Architecture

```
index.html + css/app.css + js/app.js + js/api.js
images/                  icons and the Hanu portrait
        │
        ▼
backend/main.py          FastAPI app, also serves the PWA
backend/api.py           every HTTP endpoint
backend/models.py        every Pydantic model
backend/sheets.py        every Google Sheets call
backend/hanu.py          Hanu: LangGraph, program lookups, equipment rules, OpenAI
backend/config.py        environment variables
data.json                workout programs (source of truth)
```

Python answers anything that is already determined: today's workout, completion, rest, history, and equipment limits. Hanu calls OpenAI only when the question actually needs a conversation.

There is one user for this version (`ram` by default, sent as `X-User-Id`). Login can be added later without splitting these files.

## Workout program

`data.json` has three plans:

- `schedule` — Classic Split
- `schedule_2` — Enhanced Split
- `schedule_3` — V-Tapper (the current program)

The app loads that file. The week is not copied into Python.

## Hanu

Hanu is one coach, one LangGraph workflow:

1. Classify the message in code.
2. Load the user, logs, progress, and memory in one Sheets batch.
3. Ask a clarifying question only when the answer would change.
4. Answer from the program and the logs when that is enough.
5. Call the OpenAI Responses API for open-ended coaching.
6. Save the exchange, and a memory only when it is a lasting preference.

He will not invent a previous weight. He will not recommend barbell rows, barbell squats, barbell RDLs, or cable work that is not triceps. The lat machine stays on lat and back-width work. The barbell stays on bench press.

Pain questions get one useful follow-up. Sharp or worsening pain gets a recommendation to see a clinician, not a diagnosis.

## Workout logging

Completing a set sends `POST /api/workouts/log` with exercise, set, weight, reps, optional RPE, and an optional note. The row lands in the `WorkoutLogs` tab. If the server is down, the set stays in `localStorage` and syncs on the next successful health check.

History and progression read those rows back. No separate database.

## Google Sheets

Tabs, created automatically:

| Tab | What it stores |
| --- | --- |
| Users | profile |
| WorkoutLogs | sets |
| Progress | weigh-ins |
| CoachConversations | Hanu messages |
| CoachMemory | equipment list and a few preferences |

`data.json` stays the program. Sheets is only the personal data.

Auth is the service account already proven by the old Sheets script. Nothing else calls the Google API.

## Backend setup

```bash
cd FitForge
uv sync
cp backend/.env.example backend/.env
```

Fill in `OPENAI_API_KEY` if you want open-ended Hanu replies. Today's workout, swaps, and logged weights work without it.

Point `GOOGLE_SERVICE_ACCOUNT_FILE` at a key **outside git**, or set `GOOGLE_SERVICE_ACCOUNT_JSON`. Share the spreadsheet with the service account email as an editor.

## Frontend setup

No build step. FastAPI serves the page.

```bash
cd backend
uv run uvicorn main:app --reload --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

A static server still works for the shell (`python3 -m http.server 8080`). It calls the API on port 8000. Override that with `localStorage.fitforge_api_base` if the API lives elsewhere.

## Environment variables

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | Responses API. Omit it and Hanu still answers from the program and logs. |
| `OPENAI_MODEL` | Default `gpt-4.1-mini`. |
| `GOOGLE_SPREADSHEET_ID` | The FitForge spreadsheet. |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | Path to the service-account JSON. |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Same key inline, preferred on a server. |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REDIRECT_URI` | Reserved. Not used. Sheets auth is the service account. |
| `CORS_ORIGINS` | Allowed browser origins. |
| `FITFORGE_USER_ID` | Default user id when the request has no `X-User-Id`. |

## API

| Method | Path |
| --- | --- |
| GET | `/api/health` |
| GET, PUT | `/api/user` |
| GET | `/api/workouts/today` |
| GET | `/api/workouts/schedule` |
| GET | `/api/workouts/{day}` |
| POST | `/api/workouts/log` |
| GET | `/api/workouts/history` |
| GET | `/api/workouts/history/{exercise_name}` |
| GET, POST | `/api/progress` |
| POST | `/api/coach/chat` |
| GET | `/api/coach/history` |

Send `X-User-Id` and `X-Client-Date` (`YYYY-MM-DD`). The phone date decides what "today" means.

## PWA

`manifest.json` and `sw.js` still make the app installable. The service worker caches the shell and `data.json`. It does not cache `/api/` responses.

Offline, the cached UI and the program still open. The set you just finished is queued locally. Hanu and history need the server; the screen says so instead of dumping a network error.

Theme (`fitforge_theme`), Spotify device (`fitforge_device`), plan (`fitforge_plan`), and the in-progress session (`fitforge_state`) stay on the phone.

## Tests

```bash
uv run pytest -q
```

Pytest covers today's workout, equipment rejection (cable rows, barbell squats), program substitutions, progression from real log rows, pain clarification, and a live Sheets create/read/update/delete cycle when the key file is present.

## Deployment

FastAPI serves the page and the API from one origin. `app.py` is the Vercel entrypoint. It loads the app in `backend/` without moving that code.

### Vercel

Leave the project **Root Directory** as the repository root. Clear any custom Install or Build command in the project settings. An old `uvicorn` build command will fail the deploy. Vercel detects FastAPI from `requirements.txt` and `pyproject.toml`.

Set these environment variables on the project (Production, and Preview if you use preview URLs):

| Variable | Required |
| --- | --- |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Yes. The raw key JSON, one value. Do not upload the key file. |
| `OPENAI_API_KEY` | Yes, for open-ended Hanu replies. Swaps and logged weights work without it. |
| `OPENAI_MODEL` | No. Defaults to `gpt-4.1-mini`. |
| `GOOGLE_SPREADSHEET_ID` | No, unless the sheet is not the one in `backend/config.py`. |
| `CORS_ORIGINS` | No. The phone calls the same origin. |
| `FITFORGE_USER_ID` | No. Defaults to `ram`. |

`vercel.json` gives the function 120 seconds, which covers a cold start plus a Hanu reply. Hobby allows up to 300 seconds.

Push the repo, or from this folder:

```bash
npx vercel --prod
```

### Docker

```bash
docker build -t fitforge .
docker run --rm -p 8000:8000 --env-file backend/.env fitforge
```

The container listens on `PORT` when a host sets it. `.dockerignore` keeps `backend/.env` and `sam-agent-*.json` out of the image.

Without Docker, from `backend/`:

```bash
uv run uvicorn main:app --host 0.0.0.0 --port 8000
```

## Security

`sam-agent-506413-b67261b92c1c.json` is a real Google service-account private key for `fitforgesheet@sam-agent-506413.iam.gserviceaccount.com`.

It was **not** in git history when this was checked. It is gitignored now. Do not commit it.

If that file was ever copied, synced, or shared, revoke the key in Google Cloud and create a new one. Move the new file out of this folder and set `GOOGLE_SERVICE_ACCOUNT_FILE` or `GOOGLE_SERVICE_ACCOUNT_JSON`.

The API does not send the key, the spreadsheet contents, or the OpenAI key to the browser.

## Themes

Flat Dark is the default. Minimal is the light alternative. White Clay and Neo Brutal were tied to the old card layout and are not carried into this shell. The choice is still stored in `fitforge_theme`.

## Credits

Designed by [itsmeramc](https://bikkina.vercel.app). This is a personal training tool, not medical advice.
