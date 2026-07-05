import csv
import io
from datetime import date, timedelta

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST

from . import strava as strava_lib
from . import llm as llm_lib
from . import gpx as gpx_lib
from .forms import DailyMetricForm, WorkoutForm, ZeppCsvImportForm, GpxUploadForm
from .models import DailyMetric, Activity, Workout, ChatMessage, StravaToken


def dashboard(request):
    if request.method == "POST":
        form = DailyMetricForm(request.POST)
        if form.is_valid():
            metric, _ = DailyMetric.objects.update_or_create(
                date=form.cleaned_data["date"],
                defaults={k: v for k, v in form.cleaned_data.items() if k != "date"},
            )
            messages.success(request, f"Saved metrics for {metric.date}.")
            return redirect("dashboard")
    else:
        form = DailyMetricForm(initial={"date": date.today()})

    recent_metrics = DailyMetric.objects.all()[:14]
    recent_activities = Activity.objects.all()[:10]
    strava_connected = StravaToken.objects.exists()

    return render(request, "coach/dashboard.html", {
        "form": form,
        "recent_metrics": recent_metrics,
        "recent_activities": recent_activities,
        "strava_connected": strava_connected,
        "today": date.today(),
    })


def metric_delete(request, pk):
    get_object_or_404(DailyMetric, pk=pk).delete()
    messages.success(request, "Deleted metric entry.")
    return redirect("dashboard")


def calendar_view(request):
    week_offset = int(request.GET.get("week", 0))
    today = date.today()
    start_of_week = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    days = [start_of_week + timedelta(days=i) for i in range(7)]

    workouts = Workout.objects.filter(date__gte=days[0], date__lte=days[-1])
    workouts_by_day = {d: [] for d in days}
    for w in workouts:
        workouts_by_day.setdefault(w.date, []).append(w)

    if request.method == "POST":
        form = WorkoutForm(request.POST)
        if form.is_valid():
            workout = form.save(commit=False)
            workout.source = "manual"
            workout.save()
            messages.success(request, "Workout added to calendar.")
            return redirect(f"/calendar/?week={week_offset}")
    else:
        form = WorkoutForm(initial={"date": today})

    return render(request, "coach/calendar.html", {
        "days": days,
        "workouts_by_day": workouts_by_day,
        "form": form,
        "week_offset": week_offset,
        "today": today,
    })


@require_POST
def workout_set_status(request, pk):
    workout = get_object_or_404(Workout, pk=pk)
    status = request.POST.get("status")
    if status in dict(Workout.STATUS_CHOICES):
        workout.status = status
        workout.save()
    return redirect(request.META.get("HTTP_REFERER", "calendar"))


@require_POST
def workout_delete(request, pk):
    get_object_or_404(Workout, pk=pk).delete()
    return redirect(request.META.get("HTTP_REFERER", "calendar"))


def chat_view(request):
    chat_history = ChatMessage.objects.all()[:100]
    return render(request, "coach/chat.html", {"chat_history": chat_history})


@require_POST
def chat_send(request):
    user_text = request.POST.get("message", "").strip()
    if not user_text:
        return JsonResponse({"error": "Empty message"}, status=400)

    ChatMessage.objects.create(role="user", content=user_text)

    context_str = llm_lib.build_context(
        metrics_qs=list(DailyMetric.objects.all()[:14]),
        activities_qs=list(Activity.objects.all()[:7]),
        workouts_qs=list(Workout.objects.filter(date__gte=date.today() - timedelta(days=7))[:20]),
        today=date.today(),
    )

    history = ChatMessage.objects.all().order_by("created_at")[:40]
    messages_payload = [{"role": "system", "content": llm_lib.SYSTEM_PROMPT + "\n\n" + context_str}]
    for m in history:
        messages_payload.append({"role": m.role, "content": m.content})

    raw_reply = llm_lib.call_llm(messages_payload)
    cleaned_reply, workouts_data = llm_lib.extract_workout_blocks(raw_reply)

    created_workouts = []
    for workout_data in workouts_data:
        if workout_data.get("date") and workout_data.get("title"):
            created_workouts.append(Workout.objects.create(
                date=workout_data["date"],
                title=workout_data["title"],
                description=workout_data.get("description", ""),
                workout_type=workout_data.get("workout_type", ""),
                source="llm",
            ))

    if created_workouts:
        if len(created_workouts) == 1:
            w = created_workouts[0]
            cleaned_reply += f"\n\n_Added to your calendar: {w.title} on {w.date}._"
        else:
            summary = "; ".join(f"{w.title} ({w.date})" for w in created_workouts)
            cleaned_reply += f"\n\n_Added {len(created_workouts)} workouts to your calendar: {summary}._"

    ChatMessage.objects.create(role="assistant", content=cleaned_reply)

    return JsonResponse({
        "reply": cleaned_reply,
        "workouts_added": len(created_workouts),
    })


@require_POST
def chat_clear(request):
    ChatMessage.objects.all().delete()
    return redirect("chat")


# --- Strava ---

def strava_connect(request):
    return redirect(strava_lib.get_authorize_url())


def strava_callback(request):
    code = request.GET.get("code")
    error = request.GET.get("error")
    if error:
        messages.error(request, f"Strava authorization was denied ({error}).")
        return redirect("dashboard")
    if not code:
        messages.error(request, "No code returned from Strava.")
        return redirect("dashboard")

    try:
        strava_lib.exchange_code_for_token(code)
        messages.success(request, "Strava connected!")
    except Exception as e:
        messages.error(request, f"Failed to connect Strava: {e}")
    return redirect("dashboard")


def strava_sync(request):
    count, error = strava_lib.sync_recent_activities()
    if error:
        messages.error(request, error)
    else:
        messages.success(request, f"Synced {count} activities from Strava.")
    return redirect("dashboard")


# --- GPX import ---

def gpx_upload(request):
    if request.method == "POST":
        form = GpxUploadForm(request.POST, request.FILES)
        if form.is_valid():
            imported, failed = 0, []
            for f in form.cleaned_data["gpx_files"]:
                try:
                    data = gpx_lib.parse_gpx_file(f)
                    Activity.objects.update_or_create(
                        external_id=f"gpx:{f.name}:{data['start_date'].isoformat()}",
                        source="gpx",
                        defaults={
                            "name": data["name"],
                            "activity_type": data["activity_type"],
                            "start_date": data["start_date"],
                            "distance_km": data["distance_km"],
                            "moving_time_min": data["moving_time_min"],
                            "avg_hr": data["avg_hr"],
                            "max_hr": data["max_hr"],
                            "elevation_gain_m": data["elevation_gain_m"],
                        },
                    )
                    imported += 1
                except Exception as e:
                    failed.append(f"{f.name}: {e}")

            if imported:
                messages.success(request, f"Imported {imported} activity(ies) from GPX.")
            for msg in failed:
                messages.error(request, f"Couldn't import {msg}")
            return redirect("dashboard")
    else:
        form = GpxUploadForm()
    return render(request, "coach/gpx_upload.html", {"form": form})


# --- Zepp CSV import ---

def zepp_import(request):
    result = None
    if request.method == "POST":
        form = ZeppCsvImportForm(request.POST, request.FILES)
        if form.is_valid():
            f = form.cleaned_data["csv_file"]
            date_col = form.cleaned_data["date_col"]
            hrv_col = form.cleaned_data["hrv_col"]
            rhr_col = form.cleaned_data["rhr_col"]
            sleep_col = form.cleaned_data["sleep_col"]

            text = io.TextIOWrapper(f.file, encoding="utf-8-sig")
            reader = csv.DictReader(text)
            imported, skipped = 0, 0
            for row in reader:
                raw_date = row.get(date_col)
                if not raw_date:
                    skipped += 1
                    continue
                defaults = {}
                if hrv_col and row.get(hrv_col):
                    defaults["hrv"] = _safe_float(row.get(hrv_col))
                if rhr_col and row.get(rhr_col):
                    defaults["rhr"] = _safe_int(row.get(rhr_col))
                if sleep_col and row.get(sleep_col):
                    defaults["sleep_hours"] = _safe_float(row.get(sleep_col))
                try:
                    DailyMetric.objects.update_or_create(date=raw_date[:10], defaults=defaults)
                    imported += 1
                except Exception:
                    skipped += 1
            result = f"Imported {imported} rows, skipped {skipped}."
            messages.success(request, result)
            return redirect("dashboard")
    else:
        form = ZeppCsvImportForm()
    return render(request, "coach/zepp_import.html", {"form": form, "result": result})


def _safe_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _safe_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None
