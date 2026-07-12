from datetime import date, timedelta
from django_ratelimit.decorators import ratelimit
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from django.urls import reverse_lazy
from django.contrib.auth.views import PasswordChangeView

from . import llm as llm_lib
from . import fit as fit_lib
from . import analytics
from .forms import DailyMetricForm, WorkoutForm, ActiveConditionForm, FitUploadForm, ProfileForm, GoalForm, LLMSettingsForm, StyledPasswordChangeForm
from .models import DailyMetric, ActiveCondition, Workout, ChatMessage, ChatSession, AthleteProfile, Goal, LLMSettings


class StyledPasswordChangeView(PasswordChangeView):
    form_class = StyledPasswordChangeForm
    template_name = "coach/password_change.html"
    success_url = reverse_lazy("password_change_done")


def _metrics_window(user, days=30):
    return list(DailyMetric.objects.filter(user=user, date__gte=date.today() - timedelta(days=days)).order_by("-date"))


def _get_profile(user):
    profile, _ = AthleteProfile.objects.get_or_create(user=user)
    return profile


def _next_goal(user):
    return Goal.objects.filter(user=user, event_date__gte=date.today()).order_by("event_date").first()


@login_required
def dashboard(request):
    if request.method == "POST":
        form = DailyMetricForm(request.POST)
        if form.is_valid():
            metric, _ = DailyMetric.objects.update_or_create(
                user=request.user,
                date=form.cleaned_data["date"],
                defaults={k: v for k, v in form.cleaned_data.items() if k != "date"},
            )
            messages.success(request, f"Saved metrics for {metric.date}.")
            return redirect("dashboard")
    else:
        form = DailyMetricForm(initial={"date": date.today()})

    all_recent_metrics = _metrics_window(request.user, days=30)
    display_metrics = all_recent_metrics[:14]
    recent_workouts = Workout.objects.filter(user=request.user, status="completed").order_by("-date")[:10]
    active_conditions = ActiveCondition.objects.filter(user=request.user, resolved=False)
    condition_form = ActiveConditionForm(initial={"start_date": date.today()})

    profile = _get_profile(request.user)
    profile_form = ProfileForm(instance=profile)
    goal = _next_goal(request.user)
    goal_form = GoalForm(initial={"event_date": date.today()})
    upcoming_goals = Goal.objects.filter(user=request.user, event_date__gte=date.today())

    flags = analytics.compute_flags(all_recent_metrics, active_conditions, today=date.today())

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


@login_required
def metric_delete(request, pk):
    get_object_or_404(DailyMetric, pk=pk, user=request.user).delete()
    messages.success(request, "Deleted metric entry.")
    return redirect("dashboard")


@login_required
@require_POST
def active_condition_add(request):
    form = ActiveConditionForm(request.POST)
    if form.is_valid():
        condition = form.save(commit=False)
        condition.user = request.user
        condition.save()
        messages.success(request, "Added active condition.")
    else:
        messages.error(request, "Couldn't save that condition - check the dates.")
    return redirect("dashboard")


@login_required
@require_POST
def active_condition_resolve(request, pk):
    condition = get_object_or_404(ActiveCondition, pk=pk, user=request.user)
    condition.resolved = True
    condition.save()
    messages.success(request, f"Marked '{condition.title}' as resolved.")
    return redirect("dashboard")


@login_required
@require_POST
def active_condition_delete(request, pk):
    get_object_or_404(ActiveCondition, pk=pk, user=request.user).delete()
    return redirect("dashboard")


@login_required
@require_POST
def profile_update(request):
    profile = _get_profile(request.user)
    form = ProfileForm(request.POST, instance=profile)
    if form.is_valid():
        form.save()
        messages.success(request, "Updated your profile/baselines.")
    else:
        messages.error(request, "Couldn't save the profile - check the values.")
    return redirect("dashboard")


@login_required
@require_POST
def goal_add(request):
    form = GoalForm(request.POST)
    if form.is_valid():
        goal = form.save(commit=False)
        goal.user = request.user
        goal.save()
        messages.success(request, "Added goal.")
    else:
        messages.error(request, "Couldn't save that goal - check the date.")
    return redirect("dashboard")


@login_required
@require_POST
def goal_delete(request, pk):
    get_object_or_404(Goal, pk=pk, user=request.user).delete()
    return redirect("dashboard")


@login_required
def calendar_view(request):
    week_offset = int(request.GET.get("week", 0))
    today = date.today()
    start_of_week = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    days = [start_of_week + timedelta(days=i) for i in range(7)]

    workouts = Workout.objects.filter(user=request.user, date__gte=days[0], date__lte=days[-1])
    workouts_by_day = {d: [] for d in days}
    for w in workouts:
        workouts_by_day.setdefault(w.date, []).append(w)

    if request.method == "POST":
        form = WorkoutForm(request.POST)
        if form.is_valid():
            workout = form.save(commit=False)
            workout.user = request.user
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


@login_required
@require_POST
def workout_set_status(request, pk):
    workout = get_object_or_404(Workout, pk=pk, user=request.user)
    status = request.POST.get("status")
    if status in dict(Workout.STATUS_CHOICES):
        workout.status = status
        workout.save()
    return redirect(request.META.get("HTTP_REFERER", "calendar"))


@login_required
@require_POST
def workout_delete(request, pk):
    get_object_or_404(Workout, pk=pk, user=request.user).delete()
    return redirect(request.META.get("HTTP_REFERER", "calendar"))


# --- Chat ---

@login_required
def chat_view(request, session_id=None):
    sessions = ChatSession.objects.filter(user=request.user)
    if session_id:
        session = get_object_or_404(ChatSession, pk=session_id, user=request.user)
    else:
        session = sessions.first()
        if not session:
            session = ChatSession.objects.create(user=request.user, title="New chat", mode="planner")
        return redirect("chat_session", session_id=session.pk)

    chat_history = session.messages.all()
    return render(request, "coach/chat.html", {
        "sessions": sessions,
        "session": session,
        "chat_history": chat_history,
    })


@login_required
@require_POST
def chat_new(request):
    mode = request.POST.get("mode", "planner")
    if mode not in dict(ChatSession.MODE_CHOICES):
        mode = "planner"
    title = "Just asking" if mode == "ask" else "Planning"
    session = ChatSession.objects.create(user=request.user, title=title, mode=mode)
    return redirect("chat_session", session_id=session.pk)


@login_required
@require_POST
@ratelimit(key="user", rate="30/h", block=True)
def chat_send(request, session_id):
    session = get_object_or_404(ChatSession, pk=session_id, user=request.user)
    user_text = request.POST.get("message", "").strip()
    if not user_text:
        return JsonResponse({"error": "Empty message"}, status=400)

    ChatMessage.objects.create(session=session, role="user", content=user_text)

    today = date.today()
    workouts_qs = list(Workout.objects.filter(user=request.user, date__gte=today - timedelta(days=14)).order_by("date")[:60])
    metrics_qs = _metrics_window(request.user, days=30)
    active_conditions = list(ActiveCondition.objects.filter(user=request.user, resolved=False))
    profile = _get_profile(request.user)
    llm_settings, _ = LLMSettings.objects.get_or_create(user=request.user)
    goal = _next_goal(request.user)

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

    raw_reply = llm_lib.call_llm(messages_payload, llm_settings.api_base, llm_settings.api_key, llm_settings.model)
    cleaned_reply, workouts_data = llm_lib.extract_workout_blocks(raw_reply)
    cleaned_reply, actions_data = llm_lib.extract_workout_actions(cleaned_reply)

    change_summaries = []

    if session.mode == "planner":
        for workout_data in workouts_data:
            if not (workout_data.get("date") and workout_data.get("title")):
                continue
            workout, created = Workout.objects.update_or_create(
                user=request.user,
                date=workout_data["date"],
                source="llm",
                workout_type=workout_data.get("workout_type", ""),
                defaults={
                    "title": workout_data["title"],
                    "description": workout_data.get("description", ""),
                    "status": "planned",
                    "distance_km": workout_data.get("distance_km"),
                    "moving_time_min": workout_data.get("moving_time_min"),
                    "avg_speed_kmh": workout_data.get("avg_speed_kmh"),
                    "avg_hr": workout_data.get("avg_hr"),
                    "hr_min": workout_data.get("hr_min"),
                    "interval_repeats": workout_data.get("interval_repeats"),
                    "interval_distance_m": workout_data.get("interval_distance_m"),
                    "interval_rest_seconds": workout_data.get("interval_rest_seconds"),
                },
            )
            verb = "Added" if created else "Updated"
            change_summaries.append(f"{verb}: {workout.title} on {workout.date}")

        for action in actions_data:
            workout_id = action.get("id")
            workout = Workout.objects.filter(pk=workout_id, user=request.user).first() if workout_id else None
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


@login_required
@require_POST
def chat_delete(request, session_id):
    get_object_or_404(ChatSession, pk=session_id, user=request.user).delete()
    return redirect("chat")


# --- FIT import ---

@login_required
def fit_upload(request):
    if request.method == "POST":
        form = FitUploadForm(request.POST, request.FILES)
        if form.is_valid():
            imported, failed = 0, []
            llm_settings, _ = LLMSettings.objects.get_or_create(user=request.user)
            for f in form.cleaned_data["fit_files"]:
                try:
                    data = fit_lib.parse_fit_file(f)
                    activity_date = data["start_date"].date() if hasattr(data["start_date"], "date") else data["start_date"]

                    deterministic = fit_lib.deterministic_description(data)
                    description = llm_lib.enhance_workout_description(
                        deterministic, llm_settings.api_base, llm_settings.api_key, llm_settings.model
                    )

                    Workout.objects.update_or_create(
                        user=request.user,
                        external_ref=f"fit:{f.name}:{data['start_date'].isoformat()}",
                        source="fit",
                        defaults={
                            "date": activity_date,
                            "title": data["name"],
                            "workout_type": data["activity_type"],
                            "status": "completed",
                            "description": description,
                            "distance_km": data["distance_km"],
                            "moving_time_min": data["moving_time_min"],
                            "avg_hr": data["avg_hr"],
                            "max_hr": data["max_hr"],
                            "hr_min": data["hr_min"],
                            "avg_speed_kmh": data["avg_speed_kmh"],
                            "elevation_gain_m": data["elevation_gain_m"],
                            "interval_repeats": data["interval_repeats"],
                            "interval_distance_m": data["interval_distance_m"],
                            "interval_rest_seconds": data["interval_rest_seconds"],
                            "laps_json": data["laps"],
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
        form = FitUploadForm()
    return render(request, "coach/fit_upload.html", {"form": form})

@login_required
def llm_settings_view(request):
    llm_settings, _ = LLMSettings.objects.get_or_create(user=request.user)
    if request.method == "POST":
        form = LLMSettingsForm(request.POST, instance=llm_settings)
        if form.is_valid():
            form.save()
            messages.success(request, "Saved your AI connection settings.")
            return redirect("llm_settings")
    else:
        form = LLMSettingsForm(instance=llm_settings)
    return render(request, "coach/llm_settings.html", {"form": form, "configured": llm_settings.is_configured()})