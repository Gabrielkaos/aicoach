from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("metric/<int:pk>/delete/", views.metric_delete, name="metric_delete"),

    path("calendar/", views.calendar_view, name="calendar"),
    path("workout/<int:pk>/status/", views.workout_set_status, name="workout_set_status"),
    path("workout/<int:pk>/delete/", views.workout_delete, name="workout_delete"),

    path("chat/", views.chat_view, name="chat"),
    path("chat/send/", views.chat_send, name="chat_send"),
    path("chat/clear/", views.chat_clear, name="chat_clear"),

    path("strava/connect/", views.strava_connect, name="strava_connect"),
    path("strava/callback/", views.strava_callback, name="strava_callback"),
    path("strava/sync/", views.strava_sync, name="strava_sync"),

    path("zepp/import/", views.zepp_import, name="zepp_import"),
    path("gpx/upload/", views.gpx_upload, name="gpx_upload"),
]
