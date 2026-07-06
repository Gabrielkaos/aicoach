"""Turns raw metrics/workouts into things a human or the LLM can act on: baseline comparisons,
a training-load rollup, proactive threshold-based flags (no LLM involved), and dashboard sparklines.
"""
from datetime import date as _date, timedelta


# --- Baselines ---

def rolling_average(metrics_qs, field, days=30, today=None):
    """metrics_qs: DailyMetric queryset/list. Returns the mean of `field` over the last `days`
    days, or None if there's no data in that window."""
    today = today or _date.today()
    cutoff = today - timedelta(days=days)
    vals = [getattr(m, field) for m in metrics_qs if getattr(m, field) is not None and m.date >= cutoff]
    if not vals:
        return None
    return sum(vals) / len(vals)


def effective_baseline(profile, metrics_qs, field, profile_field, today=None):
    """One source of truth per metric: a manually-entered baseline (e.g. copied from your Zepp
    app) wins if set; otherwise it's computed from your last 30 days of logged data. Returns
    (value, source_label) or (None, None) if neither is available."""
    manual = getattr(profile, profile_field, None) if profile else None
    if manual is not None:
        return manual, "your device's baseline"
    computed = rolling_average(metrics_qs, field, days=30, today=today)
    if computed is not None:
        return round(computed, 1), "your last 30 days"
    return None, None


def format_baseline_delta(value, baseline):
    """Returns a short string like '12% below baseline (67.0)', or None if there's nothing to
    compare against."""
    if value is None or baseline in (None, 0):
        return None
    pct = (value - baseline) / baseline * 100
    direction = "above" if pct >= 0 else "below"
    return f"{abs(pct):.0f}% {direction} baseline ({baseline:g})"


# --- Training load ---

def training_load_summary(completed_workouts, days, today, profile=None):
    """completed_workouts: iterable of Workout with status='completed'. Returns a short text
    block, or None if there's nothing in the window. Uses real HR-zone thresholds (%max HR) when
    a max HR is known or estimable from age; otherwise falls back to a window-relative heuristic
    (clearly labeled as approximate, since it can't tell a genuinely easy week from a hard one)."""
    window = [w for w in completed_workouts if w.date >= today - timedelta(days=days)]
    if not window:
        return None

    total_km = sum(w.distance_km or 0 for w in window)
    total_min = sum(w.moving_time_min or 0 for w in window)
    count = len(window)

    max_hr = profile.estimated_max_hr() if profile else None
    hr_values_present = [w for w in window if w.avg_hr]

    hard = easy = unclassified = 0
    zone_note = ""
    if max_hr and hr_values_present:
        threshold = max_hr * 0.80  # roughly the bottom of "hard"/threshold effort
        for w in window:
            if w.avg_hr is None:
                unclassified += 1
            elif w.avg_hr >= threshold:
                hard += 1
            else:
                easy += 1
        zone_note = f" (based on ~{threshold:.0f}bpm = 80% of an estimated max HR of {max_hr}bpm)"
    elif hr_values_present:
        # No max HR available - fall back to a self-relative heuristic. This is a weaker signal:
        # a week that was entirely easy will still call its least-easy session "hard".
        hr_values = [w.avg_hr for w in hr_values_present]
        threshold = max(hr_values) * 0.8
        for w in window:
            if w.avg_hr is None:
                unclassified += 1
            elif w.avg_hr >= threshold:
                hard += 1
            else:
                easy += 1
        zone_note = " (rough estimate relative to this window only - no max HR set, so this can't tell a genuinely easy week from a hard one)"
    else:
        unclassified = count

    parts = [f"Last {days} days: {count} completed session(s), {total_km:.1f}km total, {total_min:.0f}min total moving time."]
    if hard or easy:
        parts.append(f"Effort split: ~{hard} harder session(s) vs ~{easy} easier session(s){zone_note}" + (f", {unclassified} without HR data." if unclassified else "."))
    return " ".join(parts)


# --- Proactive flags (pure thresholds, no LLM) ---

def compute_flags(metrics_qs, active_conditions, today=None):
    """metrics_qs: DailyMetric queryset/list, most-recent-first. Returns a list of short warning
    strings for the dashboard - cheap, deterministic checks that don't need a model call."""
    today = today or _date.today()
    flags = []

    recent = sorted(metrics_qs, key=lambda m: m.date, reverse=True)[:5]
    chronological = list(reversed(recent))  # oldest first, for trend checks

    def trending(field, worse_if, label, unit):
        vals = [(m.date, getattr(m, field)) for m in chronological if getattr(m, field) is not None]
        if len(vals) < 3:
            return
        last_three = vals[-3:]
        if all(worse_if(last_three[i][1], last_three[i - 1][1]) for i in range(1, len(last_three))):
            flags.append(f"⚠️ {label} has gotten worse for {len(last_three)} days straight (now {last_three[-1][1]}{unit}).")

    trending("hrv", lambda new, old: new < old, "HRV", "ms")
    trending("rhr", lambda new, old: new > old, "Resting heart rate", "bpm")

    sleep_vals = [(m.date, m.sleep_hours) for m in chronological if m.sleep_hours is not None]
    short_sleep_streak = 0
    for _, hrs in reversed(sleep_vals):
        if hrs < 6:
            short_sleep_streak += 1
        else:
            break
    if short_sleep_streak >= 3:
        flags.append(f"⚠️ Under 6h sleep for {short_sleep_streak} nights in a row.")

    for c in active_conditions:
        days_active = (today - c.start_date).days
        if days_active >= 14:
            flags.append(f"⚠️ '{c.title}' has been active for {days_active} days - worth checking in on progress, or resolving it if it's healed.")

    return flags


# --- Dashboard sparklines ---

def sparkline_svg(values_with_dates, color="#059669", width=220, height=48):
    """values_with_dates: list of (date, value_or_None), oldest first. Returns an SVG string, or
    None if there isn't enough data to draw anything meaningful."""
    points = [(d, v) for d, v in values_with_dates if v is not None]
    if len(points) < 2:
        return None

    vals = [v for _, v in points]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    pad = 4
    n = len(points)
    step = (width - 2 * pad) / (n - 1)

    coords = []
    for i, (_, v) in enumerate(points):
        x = pad + i * step
        y = height - pad - ((v - lo) / span) * (height - 2 * pad)
        coords.append((x, y))

    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    last_x, last_y = coords[-1]
    last_val = points[-1][1]

    return f'''<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" class="w-full h-12">
  <polyline points="{polyline}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />
  <circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="3" fill="{color}" />
  <text x="{width - pad}" y="{pad + 8}" text-anchor="end" font-size="11" fill="{color}">{last_val:g}</text>
</svg>'''
