"""Parses uploaded FIT files (Garmin/ANT+ binary format) into calendar-Workout-shaped dicts.

FIT files carry much richer data than GPX: a 'session' summary, per-lap splits (laps mark natural
interval boundaries when someone manually laps their watch during work/rest segments), and a
per-second 'record' stream with heart rate, speed, cadence, and power. We use the session + lap
data for structured stats (no need to touch the raw per-second stream for that), and only scan
the record stream for a true min heart rate, since laps/session only report averages and max.
"""
import statistics
from datetime import timedelta

import fitparse


def _normalize_sport(sport, sub_sport=None):
    s = (sport or "").lower()
    if "cycl" in s or "bik" in s:
        return "ride"
    if "run" in s:
        return "run"
    if "swim" in s:
        return "swim"
    if "walk" in s or "hik" in s:
        return "walk"
    return sport or "activity"


def format_pace(distance_m, duration_s):
    """Returns a 'M:SS/km' pace string, or None if there's not enough data."""
    if not distance_m or not duration_s:
        return None
    km = distance_m / 1000.0
    if km <= 0:
        return None
    sec_per_km = duration_s / km
    m, s = divmod(int(round(sec_per_km)), 60)
    return f"{m}:{s:02d}/km"


def _lap_dict(lap_msg):
    d = {f.name: f.value for f in lap_msg}
    distance_m = d.get("total_distance")
    duration_s = d.get("total_timer_time") or d.get("total_elapsed_time")
    avg_speed = d.get("enhanced_avg_speed") or d.get("avg_speed")
    return {
        "distance_m": round(distance_m, 1) if distance_m else None,
        "duration_s": round(duration_s, 1) if duration_s else None,
        "avg_hr": d.get("avg_heart_rate"),
        "max_hr": d.get("max_heart_rate"),
        "avg_speed_kmh": round(avg_speed * 3.6, 2) if avg_speed else None,
        "pace": format_pace(distance_m, duration_s),
    }


def _summarize_intervals(laps):
    """Heuristic interval detection: if there are enough laps with a clear fast/slow split in
    speed, AND the 'work' laps are consistent with each other in duration (real interval reps
    repeat a similar effort - unlike, say, 4 uneven manual laps of one long ride), treat the
    faster half as 'work' reps and the slower half as 'rest'. Returns
    (summary_text_or_None, tagged_laps)."""
    usable = [l for l in laps if l["avg_speed_kmh"]]
    if len(laps) < 3 or len(usable) < 3:
        return None, laps

    speeds = [l["avg_speed_kmh"] for l in usable]
    median_speed = statistics.median(speeds)

    tagged = []
    for l in laps:
        segment = None
        if l["avg_speed_kmh"] is not None:
            segment = "work" if l["avg_speed_kmh"] >= median_speed else "rest"
        tagged.append({**l, "segment": segment})

    work_laps = [l for l in tagged if l["segment"] == "work"]
    rest_laps = [l for l in tagged if l["segment"] == "rest"]
    if len(work_laps) < 2 or not rest_laps:
        return None, tagged

    work_distances = [l["distance_m"] for l in work_laps if l["distance_m"]]
    work_durations = [l["duration_s"] for l in work_laps if l["duration_s"]]
    rest_durations = [l["duration_s"] for l in rest_laps if l["duration_s"]]

    if not work_distances or not work_durations:
        return None, tagged

    # Real interval reps are consistent with each other and individually short. Long, uneven
    # laps (e.g. someone hitting "lap" a few times during one long ride) shouldn't be mistaken
    # for structured intervals just because some laps were faster than others.
    mean_work_dur = statistics.mean(work_durations)
    if mean_work_dur <= 0:
        return None, tagged
    cv = (statistics.pstdev(work_durations) / mean_work_dur) if len(work_durations) > 1 else 0
    if cv > 0.5 or max(work_durations) > 1500:
        return None, tagged

    avg_work_dist = statistics.mean(work_distances)
    avg_work_dur = mean_work_dur
    pace = format_pace(avg_work_dist, avg_work_dur)
    summary = f"{len(work_laps)} x {avg_work_dist:.0f}m intervals"
    if pace:
        summary += f" @ {pace}"
    if rest_durations:
        summary += f", ~{statistics.mean(rest_durations):.0f}s rest between"

    return summary, tagged


def deterministic_description(parsed):
    """A plain, no-AI-needed summary built straight from computed stats - used as-is if AI
    enhancement is unavailable/fails, and as the input the AI enhancement step works from."""
    bits = []
    if parsed.get("distance_km"):
        bits.append(f"{parsed['distance_km']:.1f}km")
    if parsed.get("moving_time_min"):
        bits.append(f"{parsed['moving_time_min']:.0f}min")
    if parsed.get("avg_speed_kmh"):
        bits.append(f"{parsed['avg_speed_kmh']:.1f}km/h avg")
    if parsed.get("avg_hr"):
        lo = parsed.get("hr_min") or parsed["avg_hr"]
        hi = parsed.get("max_hr") or parsed["avg_hr"]
        bits.append(f"HR {lo:.0f}-{hi:.0f}bpm")
    if parsed.get("elevation_gain_m"):
        bits.append(f"{parsed['elevation_gain_m']:.0f}m elevation gain")
    if parsed.get("interval_summary"):
        bits.append(parsed["interval_summary"])
    return ", ".join(bits) if bits else "Imported activity."


def parse_fit_file(file_obj):
    """Returns a dict of activity fields, or raises ValueError if the file has no usable session."""
    fit = fitparse.FitFile(file_obj)

    sessions = list(fit.get_messages("session"))
    if not sessions:
        raise ValueError("No session summary found in this FIT file.")
    session = {f.name: f.value for f in sessions[0]}

    start_date = session.get("start_time")
    if start_date is None:
        raise ValueError("This FIT file's session has no start time.")

    total_distance = session.get("total_distance")
    total_time = session.get("total_timer_time") or session.get("total_elapsed_time")
    avg_speed = session.get("enhanced_avg_speed") or session.get("avg_speed")

    # Record stream is only needed for a true min heart rate (laps/session only give avg/max).
    hr_values = [
        f.value for msg in fit.get_messages("record") for f in msg
        if f.name == "heart_rate" and f.value is not None
    ]
    hr_min = min(hr_values) if hr_values else None

    laps = [_lap_dict(msg) for msg in fit.get_messages("lap")]
    interval_summary, tagged_laps = _summarize_intervals(laps)
    work_laps = [l for l in tagged_laps if l.get("segment") == "work"]

    return {
        "name": _normalize_sport(session.get("sport")).replace("ride", "Cycling").replace("run", "Running").title()
                or "Activity",
        "activity_type": _normalize_sport(session.get("sport")),
        "start_date": start_date,
        "distance_km": round(total_distance / 1000, 2) if total_distance else None,
        "moving_time_min": round(total_time / 60, 1) if total_time else None,
        "avg_hr": session.get("avg_heart_rate"),
        "max_hr": session.get("max_heart_rate"),
        "hr_min": hr_min,
        "avg_speed_kmh": round(avg_speed * 3.6, 2) if avg_speed else None,
        "elevation_gain_m": session.get("total_ascent"),
        "laps": tagged_laps,
        "interval_summary": interval_summary,
        "interval_repeats": len(work_laps) if interval_summary else None,
        "interval_distance_m": round(statistics.mean([l["distance_m"] for l in work_laps if l["distance_m"]]), 1)
            if interval_summary and any(l["distance_m"] for l in work_laps) else None,
        "interval_rest_seconds": round(statistics.mean(
            [l["duration_s"] for l in tagged_laps if l.get("segment") == "rest" and l["duration_s"]]
        ), 1) if interval_summary and any(l.get("segment") == "rest" for l in tagged_laps) else None,
    }
