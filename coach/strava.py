import time
from urllib.parse import urlencode

import requests
from django.conf import settings

from .models import StravaToken, Activity

AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
TOKEN_URL = "https://www.strava.com/oauth/token"
API_BASE = "https://www.strava.com/api/v3"


def get_authorize_url():
    params = {
        "client_id": settings.STRAVA_CLIENT_ID,
        "redirect_uri": settings.STRAVA_REDIRECT_URI,
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": "read,activity:read_all",
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def exchange_code_for_token(code):
    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": settings.STRAVA_CLIENT_ID,
            "client_secret": settings.STRAVA_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
        },
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    token, _ = StravaToken.objects.update_or_create(
        id=1,
        defaults={
            "access_token": data["access_token"],
            "refresh_token": data["refresh_token"],
            "expires_at": data["expires_at"],
            "athlete_id": data.get("athlete", {}).get("id"),
        },
    )
    return token


def get_valid_token():
    token = StravaToken.objects.first()
    if not token:
        return None
    if token.expires_at - 60 < time.time():
        resp = requests.post(
            TOKEN_URL,
            data={
                "client_id": settings.STRAVA_CLIENT_ID,
                "client_secret": settings.STRAVA_CLIENT_SECRET,
                "grant_type": "refresh_token",
                "refresh_token": token.refresh_token,
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        token.access_token = data["access_token"]
        token.refresh_token = data["refresh_token"]
        token.expires_at = data["expires_at"]
        token.save()
    return token


def sync_recent_activities(per_page=30):
    """Pull the most recent activities from Strava and upsert them locally."""
    token = get_valid_token()
    if not token:
        return 0, "Strava is not connected yet."

    resp = requests.get(
        f"{API_BASE}/athlete/activities",
        headers={"Authorization": f"Bearer {token.access_token}"},
        params={"per_page": per_page},
        timeout=20,
    )
    if resp.status_code != 200:
        return 0, f"Strava API error: {resp.status_code} {resp.text[:200]}"

    count = 0
    for item in resp.json():
        Activity.objects.update_or_create(
            external_id=str(item["id"]),
            source="strava",
            defaults={
                "name": item.get("name", ""),
                "activity_type": item.get("type", ""),
                "start_date": item.get("start_date"),
                "distance_km": (item.get("distance") or 0) / 1000.0,
                "moving_time_min": (item.get("moving_time") or 0) / 60.0,
                "avg_hr": item.get("average_heartrate"),
                "max_hr": item.get("max_heartrate"),
                "calories": item.get("calories"),
                "raw": item,
            },
        )
        count += 1
    return count, None
