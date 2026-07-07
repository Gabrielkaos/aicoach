# AI Coach

A small Django app that acts as a personal training coach:

- Log daily recovery metrics (HRV, resting heart rate, sleep, body battery, notes)
- Upload FIT files (Zepp, Garmin, anything) — they're parsed and dropped straight into your
  **calendar** as completed workouts, with real lap-level data: HR range (not just an average),
  pace/speed, and genuine interval structure (reps, distance, rest) detected from your watch's
  lap splits — richer than GPX, which only has a GPS track
- Flag **active conditions** (injuries, illness) that stay relevant for their whole duration, not
  just the day you mention them
- A weekly training calendar — planned, completed, and skipped sessions all in one place
- Multiple chat threads with the AI coach, in one of two modes:
  - **Planner** — the coach can add, move, edit, or remove workouts on your calendar
  - **Just asking** — talk things through with zero calendar side effects, enforced in code
- **Baseline-relative metrics**: set a manual HRV/RHR baseline (e.g. copied straight from your Zepp
  app) or let it auto-compute a rolling 30-day average — either way, every HRV/RHR shown to the
  coach comes with "X% above/below your baseline" instead of a bare number with no personal context
- **Proactive dashboard flags**: cheap, non-LLM threshold checks (HRV/RHR trending the wrong way
  for 3+ days, short sleep streaks, a condition that's been active 14+ days) surfaced automatically
  on the dashboard — you don't have to think to ask
- **Goals**: set an event (name, date, target distance) and the coach reasons about how much time
  is left to build vs. taper, instead of only ever thinking day-to-day
- A training-load summary that uses real %max-HR zones when you provide a max HR (or age, to
  estimate one) — falls back to a rough self-relative estimate otherwise, clearly labeled as such
- HRV/RHR sparklines on the dashboard, built from the same 30-day window used for baselines/flags
  so what you see matches what the coach reasons about

There's deliberately no Strava or CSV import — Strava's API now requires a paid subscription for
third-party apps, and Zepp has no public API at all, so **FIT upload is the one supported import
path** and it covers both, with richer per-lap data than GPX ever gave us.

## 1. Setup

```bash
cd aicoach
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set **LLM_API_KEY** — get a free key from [Groq](https://console.groq.com) (fast,
generous free tier, OpenAI-compatible API — this is what's configured by default). You can swap to
any other OpenAI-compatible provider (OpenRouter, Together.ai, a local Ollama server, etc.) by
changing `LLM_API_BASE` and `LLM_MODEL`.

Then:

```bash
python manage.py migrate
python manage.py createsuperuser   # optional, for /admin/
python manage.py runserver
```

Visit `http://127.0.0.1:8000/`.

## 2. Using it

- **Dashboard** (`/`): log today's HRV/RHR/sleep, see any proactive flags at the top, HRV/RHR
  sparklines over the last 14 days, manage active conditions and your goal, set baselines/max HR,
  and see your most recently completed workouts.
- **Baselines & profile**: if your Zepp app already tells you your personal HRV/RHR baseline,
  paste it in here — the coach uses it directly instead of computing its own. Leave either blank
  and it falls back to a rolling 30-day average from your logged data; there's always exactly one
  baseline per metric, never two competing numbers. Max HR (or age, to estimate 220-age) sharpens
  the training-load effort split into real HR-zone percentages instead of a self-relative guess.
- **Goal**: set an event you're training toward. It's injected into every chat so the coach can
  reason about "X weeks out" instead of only ever thinking day-to-day.
- **Import FIT** (`/fit/upload/`): upload one or more `.fit` files. Distance, moving time, HR
  range (a true min-max, not just an average), pace/speed, and elevation gain are extracted from
  the file's session summary. If your watch was manually lapped during work/rest segments, real
  interval structure (rep count, distance, rest duration) is detected from those lap splits —
  with a consistency check so a handful of uneven laps on a normal long ride isn't mistaken for
  intervals. A short natural-language description is generated from those stats via one small LLM
  call at upload time (falling back to a plain stats string if the LLM isn't configured or fails),
  so the main chat only ever reads a compact summary rather than reprocessing raw data every
  message. Everything lands directly in your calendar as a completed workout — there's no separate
  "activity feed" to keep in sync; the calendar is the single source of truth.
- **Active conditions**: add something like "Shin splints (left leg)" with a start date and an
  optional expected end date. It's injected into every chat's context for as long as it's
  unresolved, so the coach keeps steering you toward low-impact options the whole time you're
  recovering — not just on the day you first mentioned it in a note.
- **Calendar** (`/calendar/`): weekly view of planned/completed/skipped workouts, each showing
  pace/speed, HR range, elevation, and interval structure (reps/distance/rest) when available.
  Add workouts manually, mark done/skipped, or let the coach manage it via chat.
- **Chat** (`/chat/`): a sidebar lists your chat threads.
  - **Planner** threads can add new workouts (`​```workout​`) and move/edit/delete existing ones
    (`​```workout_action​`, referencing the id shown in the calendar context) — so "actually move
    that to Thursday" or "cancel Tuesday's run" works directly in conversation. When the coach
    suggests a session, it's asked to include concrete targets where relevant - pace/speed,
    duration, a target HR range, and (for interval sessions) rep count/distance/rest - not just a
    vague text description.
  - **"Just asking"** threads answer normally but are blocked in code from writing to the
    calendar at all, even if the model outputs a workout block anyway.
  - Every message includes: active conditions, your goal, your calendar from the last 14 days
    through upcoming (each entry with an id, and completed ones with real stats: HR range,
    pace/speed, interval structure), a training-load summary, and your last 30 days of recovery
    metrics shown relative to your baseline.
  - Asking to re-plan a day you've already scheduled updates that entry instead of creating a
    duplicate (only applies to AI-suggested entries of the same workout type; manual ones are
    left alone).

## 3. Notes on the "free LLM" choice

The app talks to any OpenAI-compatible `/chat/completions` endpoint. Groq is the default because
its free tier is currently one of the most usable for a small personal project (fast Llama models,
no card required). If Groq's terms or limits change, or you'd rather use something else, just
change `LLM_API_BASE` / `LLM_MODEL` / `LLM_API_KEY` in `.env` — no code changes needed.

## 4. Project layout

```
aicoach/
  aicoach/           Django project settings/urls
  coach/
    models.py         DailyMetric, ActiveCondition, AthleteProfile, Goal, Workout (unified calendar+activity), ChatSession, ChatMessage
    views.py           dashboard, calendar, chat, fit upload, active conditions, profile/goal
    llm.py             builds context + calls the LLM API + parses workout create/move/edit/delete blocks + FIT description enhancement
    analytics.py       baselines, training-load summary, proactive flags, SVG sparkline generation
    fit.py             FIT file parsing (laps, HR range, pace, interval detection)
    templates/coach/   Tailwind-styled templates (CDN, no build step)
```

## 5. Known limitations / ideas to extend

- Single-user only (no login-gated multi-tenant support) — fine for personal use, but don't deploy
  this publicly without adding auth in front of it.
- Without a max HR/age set, the hard/easy training-load split falls back to a rough heuristic
  based on relative average heart rate within the window — this is clearly labeled in the app as
  approximate, since a genuinely easy week can still get its "least easy" session called hard.
  Filling in max HR (or age) on the dashboard fixes this.
- The duplicate-workout guard is keyed on (date, workout_type, source=`llm`), so it supports
  multiple different AI-suggested sessions on the same day (e.g. cycling + strength) while still
  updating in place rather than duplicating if you re-ask for the same type of session on a day
  it's already planned that. The tradeoff: if the model phrases `workout_type` differently between
  messages (e.g. "cycling" vs "easy ride"), that could create a near-duplicate instead of updating
  - a minor edge case, but worth knowing about if you notice near-duplicates on the calendar.
- Chat threads don't share context with each other — only the underlying data (metrics, calendar,
  conditions, goal, baselines) is shared, not the conversation itself.
- Proactive flags are simple, deterministic threshold checks (not LLM calls), so they're fast and
  free but won't catch anything more nuanced than "3 days trending the wrong way" or "N days since
  a condition started."
- Interval detection from FIT files relies on your watch having actual lap splits (manual or
  auto-lap) marking work/rest boundaries, plus a consistency check (similar-duration "work" laps,
  none longer than 25 minutes) to avoid mistaking a few uneven laps of a long ride for real
  intervals. A session lapped inconsistently, or one where "work" reps genuinely vary a lot in
  length, may not get flagged as an interval workout even though it was one.
- The FIT description enhancement is one extra LLM call per uploaded file - on a very slow/rate
  limited free provider this could make bulk uploads feel sluggish; it always falls back to a
  plain (if less readable) stats string rather than failing the upload.
