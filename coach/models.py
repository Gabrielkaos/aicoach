from django.db import models


class DailyMetric(models.Model):
    """Daily wellness metrics - entered manually or imported from GPX-adjacent notes."""

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


class ActiveCondition(models.Model):
    """A standing, durable fact (injury, illness, life circumstance) that should influence
    coaching advice for as long as it's active - independent of whether today's note mentions it."""

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
    """A single calendar entry - either a planned/suggested session, or a completed activity
    imported from GPX. Unifying both in one model means the AI coach only ever needs to look at
    the calendar to know what happened and what's planned; there's no separate activity feed."""

    STATUS_CHOICES = [("planned", "Planned"), ("completed", "Completed"), ("skipped", "Skipped")]
    SOURCE_CHOICES = [("llm", "AI Coach"), ("manual", "Manual"), ("gpx", "GPX upload")]

    date = models.DateField()
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    workout_type = models.CharField(max_length=64, blank=True, help_text="e.g. easy run, intervals, cycling, strength, rest")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="planned")
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default="manual")

    # Populated for real completed activities (currently only via GPX upload).
    distance_km = models.FloatField(null=True, blank=True)
    moving_time_min = models.FloatField(null=True, blank=True)
    avg_hr = models.FloatField(null=True, blank=True)
    max_hr = models.FloatField(null=True, blank=True)
    elevation_gain_m = models.FloatField(null=True, blank=True)
    external_ref = models.CharField(max_length=255, blank=True, null=True, db_index=True,
                                     help_text="Dedup key for imports, e.g. gpx filename+timestamp")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "created_at"]

    def __str__(self):
        return f"{self.title} ({self.date})"


class AthleteProfile(models.Model):
    """Singleton-ish profile for the single user of this app. Baselines here are optional manual
    overrides (e.g. copied from your Zepp app's own baseline) - if left blank, the app computes a
    rolling 30-day average from your logged metrics instead. Either way there's one source of truth
    per metric, not two competing numbers."""

    hrv_baseline = models.FloatField(null=True, blank=True, help_text="ms - leave blank to auto-compute from your last 30 days")
    rhr_baseline = models.PositiveIntegerField(null=True, blank=True, help_text="bpm - leave blank to auto-compute from your last 30 days")
    max_hr = models.PositiveIntegerField(null=True, blank=True, help_text="Known max heart rate, if you have it")
    age = models.PositiveIntegerField(null=True, blank=True, help_text="Used to estimate max HR (220-age) if max HR isn't set")

    def __str__(self):
        return "Athlete profile"

    def estimated_max_hr(self):
        if self.max_hr:
            return self.max_hr
        if self.age:
            return 220 - self.age
        return None


class Goal(models.Model):
    """A race/event to plan training around."""

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

    title = models.CharField(max_length=255, blank=True)
    mode = models.CharField(max_length=10, choices=MODE_CHOICES, default="planner")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title or f"Chat #{self.pk}"


class ChatMessage(models.Model):
    ROLE_CHOICES = [("user", "You"), ("assistant", "Coach")]

    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name="messages", null=True, blank=True)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.role}: {self.content[:40]}"
