"""Parses uploaded GPX files into Activity-model-shaped dicts.

Heart rate lives in vendor extensions (most commonly Garmin's TrackPointExtension,
namespaced differently depending on the device/app that produced the file), so we
scan extension elements for anything that looks like a heart-rate tag rather than
relying on one fixed namespace.
"""
import gpxpy


def _find_heartrates(gpx):
    """Best-effort extraction of per-point heart rate values from GPX extensions."""
    hrs = []
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                for ext in point.extensions or []:
                    hrs.extend(_extract_hr_from_element(ext))
    return hrs


def _extract_hr_from_element(element):
    found = []
    tag = element.tag.split("}")[-1].lower()  # strip XML namespace
    if tag in ("hr", "heartrate", "heart_rate") and element.text and element.text.strip().isdigit():
        found.append(int(element.text.strip()))
    for child in element:
        found.extend(_extract_hr_from_element(child))
    return found


def parse_gpx_file(file_obj):
    """Returns a dict of activity fields, or raises ValueError if the file has no usable track."""
    gpx = gpxpy.parse(file_obj)

    if not gpx.tracks and not gpx.routes:
        raise ValueError("No tracks found in this GPX file.")

    # Prefer track data; fall back to routes if that's all the file has.
    all_points = []
    activity_type = ""
    name = gpx.name or ""

    for track in gpx.tracks:
        name = name or track.name or ""
        activity_type = activity_type or (track.type or "")
        for segment in track.segments:
            all_points.extend(segment.points)

    if not all_points:
        for route in gpx.routes:
            name = name or route.name or ""
            all_points.extend(route.points)

    if not all_points:
        raise ValueError("This GPX file doesn't contain any trackpoints.")

    start_date = all_points[0].time
    if start_date is None:
        raise ValueError("This GPX file's points have no timestamps, so a date can't be determined.")

    moving_data = gpx.get_moving_data()
    distance_km = (moving_data.moving_distance + moving_data.stopped_distance) / 1000.0 if moving_data else (
        gpx.length_3d() or gpx.length_2d() or 0
    ) / 1000.0
    moving_time_min = (moving_data.moving_time / 60.0) if moving_data else None

    uphill, downhill = gpx.get_uphill_downhill()

    heartrates = _find_heartrates(gpx)
    avg_hr = sum(heartrates) / len(heartrates) if heartrates else None
    max_hr = max(heartrates) if heartrates else None

    return {
        "name": name or "GPX activity",
        "activity_type": _normalize_type(activity_type or name),
        "start_date": start_date,
        "distance_km": round(distance_km, 2) if distance_km else None,
        "moving_time_min": round(moving_time_min, 1) if moving_time_min else None,
        "avg_hr": round(avg_hr, 1) if avg_hr else None,
        "max_hr": max_hr,
        "elevation_gain_m": round(uphill, 1) if uphill else None,
    }


def _normalize_type(raw_type):
    t = (raw_type or "").lower()
    if any(k in t for k in ("bike", "cycl", "ride")):
        return "ride"
    if any(k in t for k in ("run", "jog")):
        return "run"
    if "swim" in t:
        return "swim"
    if "walk" in t or "hik" in t:
        return "walk"
    return raw_type or "activity"
