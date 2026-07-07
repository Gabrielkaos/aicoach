import json
import re
from datetime import date as _date, timedelta

import requests
from django.conf import settings

from . import analytics

SYSTEM_PROMPT = """You are an experienced, encouraging endurance and fitness coach for the user of this app.

You are given, in the context below: the current date, any active injuries/conditions the user has
flagged (these stay relevant for their whole duration, not just on the day they were logged), any
upcoming goal/event they're training for, a unified calendar covering roughly the last two weeks
through what's upcoming (completed sessions - including ones imported from FIT files - and
planned/suggested ones, each with an id), a rough training-load summary, and recent daily recovery
metrics (HRV, resting heart rate, sleep) shown relative to the user's own baseline where one is
available. The calendar is the single source of truth for what the user has actually done and has
planned - you don't need anything else to know their recent training history.

When a metric is shown as "X% below/above baseline", that's relative to this specific person's own
normal range, not a generic population number - treat a notable deviation from their own baseline as
more meaningful than the raw number alone. If a goal/event is set, use the time remaining to it to
inform how much you can push training vs. prioritize recovery right now.

The current date given in the context is always "today" - use that exact date, and compute any
other date (tomorrow, this Monday, next week, etc.) relative to it. Never guess today's date.

Pay close attention to active conditions and to free-text notes - they often mention injuries,
pain, soreness, illness, stress, or how a session actually felt, which numbers alone won't capture.

Adapt the *type* of activity, not just the intensity, to what the user's body needs:
- If there's an active condition or a note about an impact-related issue (shin splints, runner's
  knee, IT band, stress fracture, joint pain, etc.), recommend low-impact cross-training instead of
  running - cycling, swimming, rowing, or the elliptical are all good options - and briefly explain
  why running is best avoided for now. Keep recommending this for as long as the condition is
  active, not just on the day it was first mentioned. Don't default to "rest" alone if a
  lower-impact option is reasonable; always suggest seeing a medical professional for anything that
  sounds serious, worsening, or unclear.
- If HRV is trending down, RHR is elevated, sleep has been poor, or the training-load summary shows
  a lot of hard sessions recently, favor an easy day, a shorter session, or full rest, and say why.
- If everything looks solid, it's fine to progress training normally.

Be concise and direct. Do not invent metrics, activities, or calendar entries that weren't given to
you in the context; if data is missing, say so and ask for it or give general advice instead.

--- Adding or changing calendar entries ---

To ADD a new workout, use a fenced block like this, one JSON object per block, nothing else inside
the fence. Always include specific, concrete targets where they make sense for the session -
target pace or speed, duration, a target heart-rate range, and (if it's an interval session) the
repeat count, interval distance, and rest duration - rather than a vague description:

```workout
{"date": "YYYY-MM-DD", "title": "Short title", "description": "1-2 sentence description", "workout_type": "easy run|intervals|long run|cycling|strength|rest|cross-train|swim", "distance_km": 8, "moving_time_min": 45, "avg_speed_kmh": 10.7, "hr_min": 130, "avg_hr": 145, "interval_repeats": 6, "interval_distance_m": 800, "interval_rest_seconds": 90}
```

Only include the numeric target fields that are actually relevant to that session - e.g. a rest day
needs none of them, an easy run might just have distance/time/HR range, and only an interval
session needs interval_repeats/interval_distance_m/interval_rest_seconds. hr_min and avg_hr
together describe a target HR range (low-high) for the session, not just an average.

If proposing a whole week, output multiple separate ```workout ...``` blocks like that, one per
day - never put more than one JSON object in a single fence, and never use a JSON array.

To MOVE, EDIT, or REMOVE an existing calendar entry (e.g. the user says "actually move that to
Thursday" or "cancel Tuesday's run"), use the id shown for that entry in the calendar context
above - never invent an id. Use a fenced block like this:

```workout_action
{"action": "move", "id": 12, "new_date": "YYYY-MM-DD"}
```
or
```workout_action
{"action": "update", "id": 12, "title": "...", "description": "...", "workout_type": "..."}
```
(only include the fields you want to change, plus id and action)
or
```workout_action
{"action": "delete", "id": 12}
```

Only include workout/workout_action blocks when the user actually wants something scheduled or
changed - not for general advice or when just discussing how they feel."""


def _format_metric_bits(m, profile, metrics_for_baseline, today):
    """Shared formatter used both for a workout's same-day annotation and the standalone metrics
    list, so baseline-relative deltas are computed the same way in exactly one place."""
    bits = []
    if m.hrv is not None:
        baseline, _ = analytics.effective_baseline(profile, metrics_for_baseline, "hrv", "hrv_baseline", today=today)
        delta = analytics.format_baseline_delta(m.hrv, baseline)
        bits.append(f"HRV={m.hrv}ms" + (f" ({delta})" if delta else ""))
    if m.rhr is not None:
        baseline, _ = analytics.effective_baseline(profile, metrics_for_baseline, "rhr", "rhr_baseline", today=today)
        delta = analytics.format_baseline_delta(m.rhr, baseline)
        bits.append(f"RHR={m.rhr}bpm" + (f" ({delta})" if delta else ""))
    if m.sleep_hours is not None:
        bits.append(f"sleep={m.sleep_hours}h")
    if m.sleep_score is not None:
        bits.append(f"sleep_score={m.sleep_score}")
    if m.body_battery is not None:
        bits.append(f"body_battery={m.body_battery}")
    if m.notes:
        bits.append(f"notes='{m.notes}'")
    return bits


def build_context(metrics_qs, workouts_qs, active_conditions=None, today=None, profile=None, goal=None):
    today = today or _date.today()
    metrics_by_date = {m.date: m for m in metrics_qs}
    lines = [f"Today's date is {today}.\n"]

    lines.append("=== Active conditions (relevant for their whole duration, not just today) ===")
    if active_conditions:
        for c in active_conditions:
            days_active = (today - c.start_date).days
            end = f" (expected until ~{c.expected_end_date})" if c.expected_end_date else " (no expected end date yet)"
            lines.append(f"- {c.title}, active since {c.start_date} ({days_active} days){end}. {c.description}".strip())
    else:
        lines.append("None currently flagged.")

    lines.append("\n=== Goal ===")
    if goal:
        days_away = (goal.event_date - today).days
        weeks_away = days_away / 7
        dist = f", target distance {goal.target_distance_km:g}km" if goal.target_distance_km else ""
        lines.append(f"{goal.title} on {goal.event_date} ({days_away} days / ~{weeks_away:.1f} weeks away{dist}). {goal.notes}".strip())
    else:
        lines.append("No goal/event set - treat training day-to-day unless the user mentions one.")

    hrv_baseline, hrv_src = analytics.effective_baseline(profile, metrics_qs, "hrv", "hrv_baseline", today=today)
    rhr_baseline, rhr_src = analytics.effective_baseline(profile, metrics_qs, "rhr", "rhr_baseline", today=today)
    if hrv_baseline or rhr_baseline:
        lines.append("\n=== Baselines used for comparisons below ===")
        if hrv_baseline:
            lines.append(f"HRV baseline: {hrv_baseline:g}ms ({hrv_src})")
        if rhr_baseline:
            lines.append(f"RHR baseline: {rhr_baseline:g}bpm ({rhr_src})")

    lines.append("\n=== Calendar (last 14 days through upcoming) - each entry has an id for edits ===")
    if workouts_qs:
        for w in workouts_qs:
            bits = [f"[id={w.pk}]", f"{w.date}", f"[{w.status}]", w.title]
            if w.workout_type:
                bits.append(f"({w.workout_type})")
            line = " ".join(bits)
            if w.description:
                line += f" - {w.description}"

            stat_bits = []
            if w.distance_km:
                stat_bits.append(f"{w.distance_km:.1f}km")
            if w.moving_time_min:
                stat_bits.append(f"{w.moving_time_min:.0f}min")
            if w.avg_speed_kmh:
                stat_bits.append(f"{w.avg_speed_kmh:.1f}km/h")
            if w.hr_min and w.avg_hr and w.hr_min != w.avg_hr:
                stat_bits.append(f"HR range {w.hr_min:.0f}-{w.max_hr or w.avg_hr:.0f}")
            elif w.avg_hr:
                stat_bits.append(f"avg_hr={w.avg_hr:.0f}")
            if w.elevation_gain_m:
                stat_bits.append(f"elev_gain={w.elevation_gain_m:.0f}m")
            if w.interval_repeats:
                interval_bits = [f"{w.interval_repeats}x"]
                if w.interval_distance_m:
                    interval_bits.append(f"{w.interval_distance_m:.0f}m")
                if w.interval_rest_seconds:
                    interval_bits.append(f"{w.interval_rest_seconds:.0f}s rest")
                stat_bits.append("intervals: " + " ".join(interval_bits))
            if stat_bits:
                line += " | " + ", ".join(stat_bits)

            same_day_metric = metrics_by_date.get(w.date)
            if same_day_metric:
                metric_bits = _format_metric_bits(same_day_metric, profile, metrics_qs, today)
                if metric_bits:
                    line += " | same-day: " + ", ".join(metric_bits)

            lines.append(line)
    else:
        lines.append("Nothing on the calendar yet.")

    lines.append("\n=== Training load summary ===")
    completed = [w for w in workouts_qs if w.status == "completed"]
    summary_7 = analytics.training_load_summary(completed, days=7, today=today, profile=profile)
    summary_14 = analytics.training_load_summary(completed, days=14, today=today, profile=profile)
    if summary_7:
        lines.append(summary_7)
    if summary_14:
        lines.append(summary_14)
    if not summary_7 and not summary_14:
        lines.append("No completed sessions logged in the last 14 days.")

    lines.append("\n=== Recent daily recovery metrics (most recent first, baseline-relative where possible) ===")
    if metrics_qs:
        for m in metrics_qs:
            parts = [f"{m.date}"] + _format_metric_bits(m, profile, metrics_qs, today)
            lines.append(" | ".join(parts))
    else:
        lines.append("No metrics logged yet.")

    return "\n".join(lines)


def _fenced_blocks(text, tag):
    return re.findall(rf"```{tag}\s*(.*?)```", text, re.DOTALL)


def _parse_json_tolerant(raw):
    """Tries a normal JSON parse; if that fails, tries to repair a model that glued several
    {"..."} objects together in one fence without an enclosing array."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    fixed = re.sub(r"}\s*{", "},{", raw)
    try:
        return json.loads(f"[{fixed}]")
    except json.JSONDecodeError:
        return None


def extract_workout_blocks(text):
    """Pulls all ```workout ...``` (creation) blocks out of a reply.
    Returns (cleaned_text, list_of_workout_dicts)."""
    blocks = _fenced_blocks(text, "workout(?!_action)")
    workouts = []
    for raw in blocks:
        raw = raw.strip()
        if not raw:
            continue
        parsed = _parse_json_tolerant(raw)
        if isinstance(parsed, dict):
            workouts.append(parsed)
        elif isinstance(parsed, list):
            workouts.extend(p for p in parsed if isinstance(p, dict))

    cleaned = re.sub(r"```workout(?!_action)\s*.*?```", "", text, flags=re.DOTALL).strip()
    return cleaned, workouts


def extract_workout_actions(text):
    """Pulls all ```workout_action ...``` (move/update/delete) blocks out of a reply.
    Returns (cleaned_text, list_of_action_dicts)."""
    blocks = _fenced_blocks(text, "workout_action")
    actions = []
    for raw in blocks:
        raw = raw.strip()
        if not raw:
            continue
        parsed = _parse_json_tolerant(raw)
        if isinstance(parsed, dict):
            actions.append(parsed)
        elif isinstance(parsed, list):
            actions.extend(p for p in parsed if isinstance(p, dict))

    cleaned = re.sub(r"```workout_action\s*.*?```", "", text, flags=re.DOTALL).strip()
    return cleaned, actions


def enhance_workout_description(deterministic_summary):
    """One small LLM call at ingest time to turn computed FIT stats into a natural sentence or
    two - the 'pre-process once, so the main chat only sees a compact summary' step. This is the
    same architectural idea as an ingest-time embedding/summarization stage in a RAG pipeline; it
    just uses a short LLM call over deterministic stats rather than vector embeddings, since
    embeddings are built for semantic text retrieval and don't apply well to numeric time-series
    data like a heart-rate/pace stream. Falls back to the plain deterministic text if the LLM
    isn't configured or the call fails, so an upload never breaks on this step."""
    prompt = (
        "Rewrite these computed workout stats as one or two short, natural sentences for a "
        "training log entry. Do not invent any numbers that aren't given here, and don't add "
        "commentary or advice - just describe what happened.\n\nStats: " + deterministic_summary
    )
    try:
        text = call_llm([{"role": "user", "content": prompt}])
    except Exception:
        return deterministic_summary
    if not text or text.startswith("Sorry,") or text.startswith("I don't have an LLM"):
        return deterministic_summary
    return text.strip()


def call_llm(messages):
    """messages: list of {"role": "system"|"user"|"assistant", "content": str}"""
    if not settings.LLM_API_KEY:
        return (
            "I don't have an LLM API key configured yet. Add LLM_API_KEY to your .env file "
            "(a free Groq key from https://console.groq.com works well) and reload."
        )

    url = f"{settings.LLM_API_BASE.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.LLM_MODEL,
        "messages": messages,
        "temperature": 0.6,
        "max_tokens": 1600,
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except requests.exceptions.RequestException as e:
        return f"Sorry, the LLM request failed: {e}"
    except (KeyError, IndexError):
        return "Sorry, I got an unexpected response from the LLM API."
