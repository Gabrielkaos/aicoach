from django.conf import settings
from django.db import models


class LLMSettings(models.Model):
    """Per-user LLM connection - each account brings its own API key, so nobody shares your
    Groq quota. Defaults are prefilled toward Groq's free tier, but any OpenAI-compatible
    endpoint works (OpenRouter, Together, a local Ollama server, etc)."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="llm_settings")
    api_base = models.URLField(default="https://api.groq.com/openai/v1",
                                help_text="OpenAI-compatible base URL, e.g. https://api.groq.com/openai/v1")
    api_key = models.CharField(max_length=255, blank=True, help_text="Your own API key - never shared with other users")
    model = models.CharField(max_length=100, default="llama-3.3-70b-versatile",
                              help_text="e.g. llama-3.3-70b-versatile (Groq), or a model id from your provider")

    def __str__(self):
        return f"LLM settings for {self.user.email}"

    def is_configured(self):
        return bool(self.api_key)


class DailyMetric(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="daily_metrics")
    date = models.DateField()
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
        constraints = [
            models.UniqueConstraint(fields=["user", "date"], name="unique_metric_per_user_per_day"),
        ]

    def __str__(self):
        return f"Metrics for {self.date}"


class ActiveCondition(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="active_conditions")
    title = models.CharField(max_length=255, help_text="e.g. 'Shin splints (left leg)'")
    description = models.TextField(blank=True, help_text="Details, cause, what to avoid, etc.")
    start_date = models.DateField()
    expected_end_date = models.DateField(null=True, blank=True, help_text="Leave blank if unknown")
    resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date"]

    def __str__(self):
        return f"{self.title} ({'resolved' if self.resolved else 'active'})"


class Workout(models.Model):
    STATUS_CHOICES = [("planned", "Planned"), ("completed", "Completed"), ("skipped", "Skipped")]
    SOURCE_CHOICES = [("llm", "AI Coach"), ("manual", "Manual"), ("fit", "FIT upload")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="workouts")
    date = models.DateField()
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    workout_type = models.CharField(max_length=64, blank=True, help_text="e.g. easy run, intervals, cycling, strength, rest")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="planned")
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default="manual")

    distance_km = models.FloatField(null=True, blank=True)
    moving_time_min = models.FloatField(null=True, blank=True)
    avg_hr = models.FloatField(null=True, blank=True)
    max_hr = models.FloatField(null=True, blank=True)
    hr_min = models.FloatField(null=True, blank=True, help_text="Lowest HR seen (completed) or bottom of a target HR range (planned)")
    avg_speed_kmh = models.FloatField(null=True, blank=True)
    elevation_gain_m = models.FloatField(null=True, blank=True)

    interval_repeats = models.PositiveIntegerField(null=True, blank=True)
    interval_distance_m = models.FloatField(null=True, blank=True)
    interval_rest_seconds = models.FloatField(null=True, blank=True)
    laps_json = models.JSONField(null=True, blank=True, help_text="Raw per-lap splits, if imported from a FIT file")

    external_ref = models.CharField(max_length=255, blank=True, null=True, db_index=True,
                                     help_text="Dedup key for imports, e.g. fit filename+timestamp")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "created_at"]

    def __str__(self):
        return f"{self.title} ({self.date})"


class AthleteProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    hrv_baseline = models.FloatField(null=True, blank=True, help_text="ms - leave blank to auto-compute from your last 30 days")
    rhr_baseline = models.PositiveIntegerField(null=True, blank=True, help_text="bpm - leave blank to auto-compute from your last 30 days")
    max_hr = models.PositiveIntegerField(null=True, blank=True, help_text="Known max heart rate, if you have it")
    age = models.PositiveIntegerField(null=True, blank=True, help_text="Used to estimate max HR (220-age) if max HR isn't set")

    def __str__(self):
        return f"Profile for {self.user.email}"

    def estimated_max_hr(self):
        if self.max_hr:
            return self.max_hr
        if self.age:
            return 220 - self.age
        return None


class Goal(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="goals")
    title = models.CharField(max_length=255, help_text="e.g. 'City Marathon'")
    event_date = models.DateField()
    target_distance_km = models.FloatField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["event_date"]

    def __str__(self):
        return f"{self.title} ({self.event_date})"


class ChatSession(models.Model):
    MODE_CHOICES = [("planner", "Planner (can edit calendar)"), ("ask", "Just ask (no calendar changes)")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_sessions")
    title = models.CharField(max_length=255, blank=True)
    mode = models.CharField(max_length=10, choices=MODE_CHOICES, default="planner")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title or f"Chat #{self.pk}"


class ChatMessage(models.Model):
    ROLE_CHOICES = [("user", "You"), ("assistant", "Coach")]

    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.role}: {self.content[:40]}"