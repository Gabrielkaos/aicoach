from django.db import models


class DailyMetric(models.Model):
    """Daily wellness metrics - entered manually or imported from a CSV export
    (e.g. Zepp's GDPR data export) since Zepp has no public developer API."""

    date = models.DateField(unique=True)
    hrv = models.FloatField(null=True, blank=True, help_text="ms")
    rhr = models.PositiveIntegerField(null=True, blank=True, help_text="resting heart rate, bpm")
    sleep_hours = models.FloatField(null=True, blank=True)
    sleep_score = models.PositiveIntegerField(null=True, blank=True, help_text="0-100 if your device provides one")
    body_battery = models.PositiveIntegerField(null=True, blank=True, help_text="0-100 readiness/energy score, if available")
    weight_kg = models.FloatField(null=True, blank=True)
    notes = models.TextField(blank=True, help_text="How you feel, soreness, stress, life stuff, etc.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"Metrics for {self.date}"


class Activity(models.Model):
    """Completed training activities, pulled from Strava or imported manually/from Zepp CSV."""

    SOURCE_CHOICES = [("strava", "Strava"), ("zepp", "Zepp"), ("gpx", "GPX upload"), ("manual", "Manual")]

    external_id = models.CharField(max_length=64, blank=True, null=True, db_index=True)
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default="manual")
    name = models.CharField(max_length=255, blank=True)
    activity_type = models.CharField(max_length=64, blank=True)
    start_date = models.DateTimeField()
    distance_km = models.FloatField(null=True, blank=True)
    moving_time_min = models.FloatField(null=True, blank=True)
    avg_hr = models.FloatField(null=True, blank=True)
    max_hr = models.FloatField(null=True, blank=True)
    calories = models.FloatField(null=True, blank=True)
    elevation_gain_m = models.FloatField(null=True, blank=True)
    raw = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ["-start_date"]
        verbose_name_plural = "activities"

    def __str__(self):
        return f"{self.activity_type} on {self.start_date:%Y-%m-%d}"


class Workout(models.Model):
    """A planned (or completed) item on the training calendar."""

    STATUS_CHOICES = [("planned", "Planned"), ("completed", "Completed"), ("skipped", "Skipped")]
    SOURCE_CHOICES = [("llm", "AI Coach"), ("manual", "Manual")]

    date = models.DateField()
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    workout_type = models.CharField(max_length=64, blank=True, help_text="e.g. easy run, intervals, strength, rest")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="planned")
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default="manual")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "created_at"]

    def __str__(self):
        return f"{self.title} ({self.date})"


class ChatMessage(models.Model):
    ROLE_CHOICES = [("user", "You"), ("assistant", "Coach")]

    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.role}: {self.content[:40]}"


class StravaToken(models.Model):
    """Singleton-ish token store for the single user of this app."""

    access_token = models.CharField(max_length=255)
    refresh_token = models.CharField(max_length=255)
    expires_at = models.BigIntegerField()
    athlete_id = models.BigIntegerField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Strava token (athlete {self.athlete_id})"
