from datetime import date, timedelta

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST

from . import llm as llm_lib
from . import gpx as gpx_lib
from . import analytics
from .forms import DailyMetricForm, WorkoutForm, ActiveConditionForm, GpxUploadForm, ProfileForm, GoalForm
from .models import DailyMetric, ActiveCondition, Workout, ChatMessage, ChatSession, AthleteProfile, Goal


def _metrics_window(days=30):
    """Single shared query for 'recent metrics' - used for display, baselines, and flags alike,
    so there's one window definition instead of several different hardcoded slices."""
    return list(DailyMetric.objects.filter(date__gte=date.today() - timedelta(days=days)).order_by("-date"))


def _get_profile():
    profile = AthleteProfile.objects.first()
    if not profile:
        profile = AthleteProfile.objects.create()
    return profile


def _next_goal():
    return Goal.objects.filter(event_date__gte=date.today()).order_by("event_date").first()


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

    all_recent_metrics = _metrics_window(days=30)  # used for baselines + flags
    display_metrics = all_recent_metrics[:14]       # what actually shows in the table
    recent_workouts = Workout.objects.filter(status="completed").order_by("-date")[:10]
    active_conditions = ActiveCondition.objects.filter(resolved=False)
    condition_form = ActiveConditionForm(initial={"start_date": date.today()})

    profile = _get_profile()
    profile_form = ProfileForm(instance=profile)
    goal = _next_goal()
    goal_form = GoalForm(initial={"event_date": date.today()})
    upcoming_goals = Goal.objects.filter(event_date__gte=date.today())

    flags = analytics.compute_flags(all_recent_metrics, active_conditions, today=date.today())

    # Sparklines want oldest-first
    chronological = list(reversed(display_metrics))
    hrv_svg = analytics.sparkline_svg([(m.date, m.hrv) for m in chronological], color="#059669")
    rhr_svg = analytics.sparkline_svg([(m.date, m.rhr) for m in chronological], color="#e11d48")

    return render(request, "coach/dashboard.html", {
        "form": form,
        "condition_form": condition_form,
        "recent_metrics": display_metrics,
        "recent_workouts": recent_workouts,
        "active_conditions": active_conditions,
        "hrv_svg": hrv_svg,
        "rhr_svg": rhr_svg,
        "flags": flags,
        "profile_form": profile_form,
        "goal_form": goal_form,
        "goal": goal,
        "upcoming_goals": upcoming_goals,
        "today": date.today(),
    })


def metric_delete(request, pk):
    get_object_or_404(DailyMetric, pk=pk).delete()
    messages.success(request, "Deleted metric entry.")
    return redirect("dashboard")


@require_POST
def active_condition_add(request):
    form = ActiveConditionForm(request.POST)
    if form.is_valid():
        form.save()
        messages.success(request, "Added active condition.")
    else:
        messages.error(request, "Couldn't save that condition - check the dates.")
    return redirect("dashboard")


@require_POST
def active_condition_resolve(request, pk):
    condition = get_object_or_404(ActiveCondition, pk=pk)
    condition.resolved = True
    condition.save()
    messages.success(request, f"Marked '{condition.title}' as resolved.")
    return redirect("dashboard")


@require_POST
def active_condition_delete(request, pk):
    get_object_or_404(ActiveCondition, pk=pk).delete()
    return redirect("dashboard")


@require_POST
def profile_update(request):
    profile = _get_profile()
    form = ProfileForm(request.POST, instance=profile)
    if form.is_valid():
        form.save()
        messages.success(request, "Updated your profile/baselines.")
    else:
        messages.error(request, "Couldn't save the profile - check the values.")
    return redirect("dashboard")


@require_POST
def goal_add(request):
    form = GoalForm(request.POST)
    if form.is_valid():
        form.save()
        messages.success(request, "Added goal.")
    else:
        messages.error(request, "Couldn't save that goal - check the date.")
    return redirect("dashboard")


@require_POST
def goal_delete(request, pk):
    get_object_or_404(Goal, pk=pk).delete()
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


# --- Chat ---

def chat_view(request, session_id=None):
    sessions = ChatSession.objects.all()
    if session_id:
        session = get_object_or_404(ChatSession, pk=session_id)
    else:
        session = sessions.first()
        if not session:
            session = ChatSession.objects.create(title="New chat", mode="planner")
        return redirect("chat_session", session_id=session.pk)

    chat_history = session.messages.all()
    return render(request, "coach/chat.html", {
        "sessions": sessions,
        "session": session,
        "chat_history": chat_history,
    })


@require_POST
def chat_new(request):
    mode = request.POST.get("mode", "planner")
    if mode not in dict(ChatSession.MODE_CHOICES):
        mode = "planner"
    title = "Just asking" if mode == "ask" else "Planning"
    session = ChatSession.objects.create(title=title, mode=mode)
    return redirect("chat_session", session_id=session.pk)


@require_POST
def chat_send(request, session_id):
    session = get_object_or_404(ChatSession, pk=session_id)
    user_text = request.POST.get("message", "").strip()
    if not user_text:
        return JsonResponse({"error": "Empty message"}, status=400)

    ChatMessage.objects.create(session=session, role="user", content=user_text)

    today = date.today()
    workouts_qs = list(Workout.objects.filter(date__gte=today - timedelta(days=14)).order_by("date")[:60])
    metrics_qs = _metrics_window(days=30)
    active_conditions = list(ActiveCondition.objects.filter(resolved=False))
    profile = _get_profile()
    goal = _next_goal()

    context_str = llm_lib.build_context(
        metrics_qs=metrics_qs,
        workouts_qs=workouts_qs,
        active_conditions=active_conditions,
        today=today,
        profile=profile,
        goal=goal,
    )

    system_prompt = llm_lib.SYSTEM_PROMPT
    if session.mode == "ask":
        system_prompt += (
            "\n\nThe user is in 'just asking' mode right now: give advice and answer questions "
            "normally, but do NOT output any ```workout``` or ```workout_action``` block in this "
            "reply - just talk it through in plain text, even if you'd normally suggest scheduling "
            "or changing something."
        )

    history = session.messages.order_by("created_at")[:40]
    messages_payload = [{"role": "system", "content": system_prompt + "\n\n" + context_str}]
    for m in history:
        messages_payload.append({"role": m.role, "content": m.content})

    raw_reply = llm_lib.call_llm(messages_payload)
    cleaned_reply, workouts_data = llm_lib.extract_workout_blocks(raw_reply)
    cleaned_reply, actions_data = llm_lib.extract_workout_actions(cleaned_reply)

    change_summaries = []

    if session.mode == "planner":
        for workout_data in workouts_data:
            if not (workout_data.get("date") and workout_data.get("title")):
                continue
            # Duplicate guard: keyed on (date, workout_type) so a same-day re-plan of the SAME
            # type of session (e.g. re-suggesting today's cycling ride) updates in place, but two
            # different types on the same day (e.g. cycling + strength) are both kept - fixed
            # after this used to be keyed on date alone, which let a second workout on the same
            # day silently overwrite the first regardless of type.
            workout, created = Workout.objects.update_or_create(
                date=workout_data["date"],
                source="llm",
                workout_type=workout_data.get("workout_type", ""),
                defaults={
                    "title": workout_data["title"],
                    "description": workout_data.get("description", ""),
                    "status": "planned",
                },
            )
            verb = "Added" if created else "Updated"
            change_summaries.append(f"{verb}: {workout.title} on {workout.date}")

        for action in actions_data:
            workout_id = action.get("id")
            workout = Workout.objects.filter(pk=workout_id).first() if workout_id else None
            if not workout:
                change_summaries.append(f"Couldn't find a calendar entry with id={workout_id}")
                continue

            act = action.get("action")
            if act == "move" and action.get("new_date"):
                workout.date = action["new_date"]
                workout.save()
                change_summaries.append(f"Moved '{workout.title}' to {workout.date}")
            elif act == "update":
                for field in ("title", "description", "workout_type"):
                    if action.get(field):
                        setattr(workout, field, action[field])
                workout.save()
                change_summaries.append(f"Updated '{workout.title}'")
            elif act == "delete":
                title = workout.title
                workout.delete()
                change_summaries.append(f"Removed '{title}' from your calendar")

    if change_summaries:
        cleaned_reply += "\n\n_" + "; ".join(change_summaries) + "._"

    ChatMessage.objects.create(session=session, role="assistant", content=cleaned_reply)

    return JsonResponse({
        "reply": cleaned_reply,
        "changes": len(change_summaries),
    })


@require_POST
def chat_delete(request, session_id):
    get_object_or_404(ChatSession, pk=session_id).delete()
    return redirect("chat")


# --- GPX import ---

def gpx_upload(request):
    if request.method == "POST":
        form = GpxUploadForm(request.POST, request.FILES)
        if form.is_valid():
            imported, failed = 0, []
            for f in form.cleaned_data["gpx_files"]:
                try:
                    data = gpx_lib.parse_gpx_file(f)
                    activity_date = data["start_date"].date() if hasattr(data["start_date"], "date") else data["start_date"]
                    Workout.objects.update_or_create(
                        external_ref=f"gpx:{f.name}:{data['start_date'].isoformat()}",
                        source="gpx",
                        defaults={
                            "date": activity_date,
                            "title": data["name"],
                            "workout_type": data["activity_type"],
                            "status": "completed",
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
                messages.success(request, f"Imported {imported} activity(ies) into your calendar.")
            for msg in failed:
                messages.error(request, f"Couldn't import {msg}")
            return redirect("dashboard")
    else:
        form = GpxUploadForm()
    return render(request, "coach/gpx_upload.html", {"form": form})
