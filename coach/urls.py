from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("metric/<int:pk>/delete/", views.metric_delete, name="metric_delete"),

    path("condition/add/", views.active_condition_add, name="active_condition_add"),
    path("condition/<int:pk>/resolve/", views.active_condition_resolve, name="active_condition_resolve"),
    path("condition/<int:pk>/delete/", views.active_condition_delete, name="active_condition_delete"),

    path("profile/update/", views.profile_update, name="profile_update"),
    path("goal/add/", views.goal_add, name="goal_add"),
    path("goal/<int:pk>/delete/", views.goal_delete, name="goal_delete"),

    path("calendar/", views.calendar_view, name="calendar"),
    path("workout/<int:pk>/status/", views.workout_set_status, name="workout_set_status"),
    path("workout/<int:pk>/delete/", views.workout_delete, name="workout_delete"),

    path("chat/", views.chat_view, name="chat"),
    path("chat/new/", views.chat_new, name="chat_new"),
    path("chat/<int:session_id>/", views.chat_view, name="chat_session"),
    path("chat/<int:session_id>/send/", views.chat_send, name="chat_send"),
    path("chat/<int:session_id>/delete/", views.chat_delete, name="chat_delete"),

    path("gpx/upload/", views.gpx_upload, name="gpx_upload"),
]
