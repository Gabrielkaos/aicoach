# AI Coach

A small Django app that acts as a personal training coach:

- Log daily metrics (HRV, resting heart rate, sleep, body battery, notes)
- Connect Strava to auto-pull completed activities (real OAuth2 integration — note: as of June 30,
  2026 Strava requires an active Strava subscription for Standard-tier API access, so this is
  entirely optional)
- Upload GPX files (from Zepp, Garmin, etc.) to import activities — distance, moving time,
  elevation gain, and heart rate (when present) are parsed automatically
- Import Zepp recovery metrics via CSV (Zepp has **no public API** — see note below)
- Weekly training calendar
- Chat with an LLM "coach" that sees your last 7 activities (each paired with that day's metrics
  and notes), your recent recovery data, and your calendar as context — including free-text notes
  like injuries, so it can suggest cycling or swimming instead of running when that's what your
  body needs, not just a workout — and can add/adjust workouts on your calendar directly from the
  conversation

## 1. Setup

```bash
cd aicoach
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:

- **LLM_API_KEY** — get a free key from [Groq](https://console.groq.com) (fast, generous free
  tier, OpenAI-compatible API — this is what's configured by default). You can swap to any other
  OpenAI-compatible provider (OpenRouter, Together.ai, a local Ollama server, etc.) by changing
  `LLM_API_BASE` and `LLM_MODEL`.
- **STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET** — create an API app at
  [strava.com/settings/api](https://www.strava.com/settings/api). Set "Authorization Callback
  Domain" to `127.0.0.1` for local dev.

Then:

```bash
python manage.py migrate
python manage.py createsuperuser   # optional, for /admin/
python manage.py runserver
```

Visit `http://127.0.0.1:8000/`.

## 2. Using it

- **Dashboard** (`/`): log today's HRV/RHR/sleep, connect & sync Strava, see recent entries.
- **Calendar** (`/calendar/`): weekly view of planned/completed workouts. Add workouts manually,
  mark done/skipped, or let the coach schedule them via chat.
- **Chat** (`/chat/`): ask things like *"How am I recovering, and what should today's session
  look like?"* or *"Plan an easy week, I'm feeling run down."* The coach's system prompt is fed
  your last 7 activities (each matched up with that day's HRV/RHR/sleep/notes if you logged them),
  your last 14 days of metrics, and this week's calendar. If you've logged a note like "recovering
  from shin splints," it's instructed to favor low-impact options like cycling or swimming over
  running, and to explain why. When it proposes a concrete workout, it's added to your calendar
  right away (tagged with a 🤖).
- **Import GPX** (`/gpx/upload/`): upload one or more `.gpx` files (exported from Zepp, Strava,
  Garmin, etc.) and they're parsed into activities with distance, moving time, elevation gain, and
  heart rate (if the file includes it via device extensions).
- **Import CSV** (`/zepp/import/`): Zepp/Mi Fit doesn't expose a public developer API, so there's
  no live sync path. Request a data export from the app (Profile → Privacy) or via a GDPR request,
  then upload the CSV here — you tell the importer which column names map to date/HRV/RHR/sleep,
  since export formats change between app versions.

## 3. Notes on the "free LLM" choice

The app talks to any OpenAI-compatible `/chat/completions` endpoint. Groq is the default because
its free tier is currently one of the most usable for a small personal project (fast Llama models,
no card required). If Groq's terms or limits change, or you'd rather use something else, just
change `LLM_API_BASE` / `LLM_MODEL` / `LLM_API_KEY` in `.env` — no code changes needed.

## 4. Notes on Strava

The Strava integration is fully functional: it does the real OAuth2 handshake, stores tokens in
the DB, refreshes them automatically, and pulls your recent activities into the `Activity` model.
This app is built for a single user (whoever's running it) — tokens aren't scoped per-Django-user.

## 5. Project layout

```
aicoach/
  aicoach/          Django project settings/urls
  coach/
    models.py        DailyMetric, Activity, Workout, ChatMessage, StravaToken
    views.py         dashboard, calendar, chat, strava OAuth, CSV import
    llm.py           builds context + calls the LLM API + parses workout suggestions
    strava.py        OAuth + activity sync helpers
    templates/coach/ Tailwind-styled templates (CDN, no build step)
```

## 6. Known limitations / ideas to extend

- Single-user only (no login-gated multi-tenant support) — fine for personal use, but don't deploy
  this publicly without adding auth in front of it.
- The LLM's workout-suggestion format is a simple fenced JSON block it's prompted to emit; if the
  model ignores the format occasionally, the reply just won't create a calendar entry that turn.
- No push/pull for Garmin, Apple Health, etc. — Strava's API can ingest activities from most of
  those, so syncing through Strava is usually the easiest path if you use another watch.
