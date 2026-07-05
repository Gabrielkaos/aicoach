import json
import re
import requests
from django.conf import settings

SYSTEM_PROMPT = """You are an experienced, encouraging endurance and fitness coach for the user of this app.
You have access to their recent recovery metrics (HRV, resting heart rate, sleep), their last several
completed activities (each paired with that day's metrics/notes when available), and their upcoming
planned calendar. Use that context to give specific, practical advice about what they should do today,
and to adjust upcoming training if their recovery data or notes suggest it.

The current date will be given to you at the start of the context below - always use that exact date
for "today", and compute any other date (tomorrow, this Monday, next week, etc.) relative to it. Never
guess or assume today's date from the conversation alone.

Pay close attention to free-text notes attached to metrics or activities - they often mention injuries,
pain, soreness, illness, stress, or how a session actually felt, which numbers alone won't capture.

Adapt the *type* of activity, not just the intensity, to what the user's body needs:
- If notes mention an impact-related issue (shin splints, runner's knee, IT band, stress fracture,
  joint pain, etc.), recommend low-impact cross-training instead of running - cycling, swimming,
  rowing, or the elliptical are all good options - and briefly explain why running is best avoided
  for now. Don't default to "rest" alone if a lower-impact option is reasonable and the user isn't
  reporting an acute or worsening injury; but always suggest seeing a medical professional for
  anything that sounds serious, worsening, or unclear.
- If HRV is trending down, RHR is elevated, or sleep has been poor over the last few days, favor
  an easy day, a shorter session, or full rest over a hard workout, and say why.
- If everything looks solid, it's fine to progress training normally.

When you want to add or change workouts on the user's calendar, put each one in its own fenced
block using exactly this format, with ONE JSON object per block and nothing else inside the fence:

```workout
{"date": "YYYY-MM-DD", "title": "Short title", "description": "1-2 sentence description", "workout_type": "easy run|intervals|long run|cycling|strength|rest|cross-train|swim"}
```

If you're proposing a whole week, output multiple separate ```workout ...``` blocks like that, one
per day - do not put more than one JSON object inside a single fence, and do not use a JSON array.
Only include these blocks when proposing concrete, schedulable workouts - not for general advice."""


def build_context(metrics_qs, activities_qs, workouts_qs, today=None):
    from datetime import date as _date
    lines = [f"Today's date is {today or _date.today()}.\n"]
    metrics_by_date = {m.date: m for m in metrics_qs}

    lines.append("=== Last activities, each paired with that day's metrics/notes if logged ===")
    if activities_qs:
        for a in activities_qs:
            activity_date = a.start_date.date() if hasattr(a.start_date, "date") else a.start_date
            parts = [
                f"{activity_date} {a.activity_type or 'activity'}",
                f"{a.distance_km:.1f}km" if a.distance_km else None,
                f"{a.moving_time_min:.0f}min" if a.moving_time_min else None,
                f"avg_hr={a.avg_hr:.0f}" if a.avg_hr else None,
                f"elev_gain={a.elevation_gain_m:.0f}m" if a.elevation_gain_m else None,
                f"(source: {a.source})",
            ]
            line = " ".join(p for p in parts if p)

            same_day_metric = metrics_by_date.get(activity_date)
            if same_day_metric:
                metric_bits = []
                if same_day_metric.hrv is not None:
                    metric_bits.append(f"HRV={same_day_metric.hrv}ms")
                if same_day_metric.rhr is not None:
                    metric_bits.append(f"RHR={same_day_metric.rhr}bpm")
                if same_day_metric.sleep_hours is not None:
                    metric_bits.append(f"sleep={same_day_metric.sleep_hours}h")
                if same_day_metric.notes:
                    metric_bits.append(f"notes='{same_day_metric.notes}'")
                if metric_bits:
                    line += " | same-day: " + ", ".join(metric_bits)

            lines.append(line)
    else:
        lines.append("No recent activities on record.")

    lines.append("\n=== All recent daily metrics (most recent first, includes days with no activity) ===")
    if metrics_qs:
        for m in metrics_qs:
            parts = [f"{m.date}"]
            if m.hrv is not None:
                parts.append(f"HRV={m.hrv}ms")
            if m.rhr is not None:
                parts.append(f"RHR={m.rhr}bpm")
            if m.sleep_hours is not None:
                parts.append(f"sleep={m.sleep_hours}h")
            if m.sleep_score is not None:
                parts.append(f"sleep_score={m.sleep_score}")
            if m.body_battery is not None:
                parts.append(f"body_battery={m.body_battery}")
            if m.notes:
                parts.append(f"notes='{m.notes}'")
            lines.append(" | ".join(parts))
    else:
        lines.append("No metrics logged yet.")

    lines.append("\n=== Upcoming / this week's calendar ===")
    if workouts_qs:
        for w in workouts_qs:
            lines.append(f"{w.date} [{w.status}] {w.title} ({w.workout_type or 'n/a'}) - {w.description}")
    else:
        lines.append("Nothing scheduled yet.")

    return "\n".join(lines)


def extract_workout_blocks(text):
    """Pull all ```workout ...``` fenced blocks out of the LLM reply.

    Tolerates a few ways the model might format them: one JSON object per fence
    (the requested format), a JSON array inside one fence, or - since models don't
    always follow instructions - several JSON objects concatenated in one fence
    without an enclosing array. Returns (cleaned_text, list_of_workout_dicts).
    """
    blocks = re.findall(r"```workout\s*(.*?)```", text, re.DOTALL)
    workouts = []
    for raw in blocks:
        raw = raw.strip()
        if not raw:
            continue
        parsed = _parse_workout_json(raw)
        if isinstance(parsed, dict):
            workouts.append(parsed)
        elif isinstance(parsed, list):
            workouts.extend(p for p in parsed if isinstance(p, dict))

    cleaned = re.sub(r"```workout\s*.*?```", "", text, flags=re.DOTALL).strip()
    return cleaned, workouts


def _parse_workout_json(raw):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Handle several {"date": ...} {"date": ...} objects glued together in one fence.
    fixed = re.sub(r"}\s*{", "},{", raw)
    try:
        return json.loads(f"[{fixed}]")
    except json.JSONDecodeError:
        return None


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
