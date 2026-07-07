from django import forms
from .models import DailyMetric, Workout, ActiveCondition, AthleteProfile, Goal

INPUT_CLS = "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"


class DailyMetricForm(forms.ModelForm):
    class Meta:
        model = DailyMetric
        fields = ["date", "hrv", "rhr", "sleep_hours", "sleep_score", "body_battery", "weight_kg", "notes"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date", "class": INPUT_CLS}),
            "hrv": forms.NumberInput(attrs={"class": INPUT_CLS, "step": "0.1"}),
            "rhr": forms.NumberInput(attrs={"class": INPUT_CLS}),
            "sleep_hours": forms.NumberInput(attrs={"class": INPUT_CLS, "step": "0.1"}),
            "sleep_score": forms.NumberInput(attrs={"class": INPUT_CLS}),
            "body_battery": forms.NumberInput(attrs={"class": INPUT_CLS}),
            "weight_kg": forms.NumberInput(attrs={"class": INPUT_CLS, "step": "0.1"}),
            "notes": forms.Textarea(attrs={"rows": 2, "class": INPUT_CLS}),
        }


class WorkoutForm(forms.ModelForm):
    class Meta:
        model = Workout
        fields = ["date", "title", "workout_type", "description", "status"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date", "class": INPUT_CLS}),
            "title": forms.TextInput(attrs={"class": INPUT_CLS}),
            "workout_type": forms.TextInput(attrs={"class": INPUT_CLS, "placeholder": "easy run, strength, rest..."}),
            "description": forms.Textarea(attrs={"rows": 2, "class": INPUT_CLS}),
            "status": forms.Select(attrs={"class": INPUT_CLS}),
        }


class ActiveConditionForm(forms.ModelForm):
    class Meta:
        model = ActiveCondition
        fields = ["title", "description", "start_date", "expected_end_date"]
        widgets = {
            "title": forms.TextInput(attrs={"class": INPUT_CLS, "placeholder": "e.g. Shin splints (left leg)"}),
            "description": forms.Textarea(attrs={"rows": 2, "class": INPUT_CLS}),
            "start_date": forms.DateInput(attrs={"type": "date", "class": INPUT_CLS}),
            "expected_end_date": forms.DateInput(attrs={"type": "date", "class": INPUT_CLS}),
        }


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """Standard Django recipe for accepting several files from one <input multiple>."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput(attrs={"class": INPUT_CLS}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if isinstance(data, (list, tuple)):
            return [single_file_clean(d, initial) for d in data]
        return single_file_clean(data, initial)


class FitUploadForm(forms.Form):
    fit_files = MultipleFileField(help_text="Select one or more .fit files exported from Zepp, Garmin, etc.")


class ProfileForm(forms.ModelForm):
    class Meta:
        model = AthleteProfile
        fields = ["hrv_baseline", "rhr_baseline", "max_hr", "age"]
        widgets = {
            "hrv_baseline": forms.NumberInput(attrs={"class": INPUT_CLS, "step": "0.1", "placeholder": "e.g. 65 (from Zepp)"}),
            "rhr_baseline": forms.NumberInput(attrs={"class": INPUT_CLS, "placeholder": "e.g. 52 (from Zepp)"}),
            "max_hr": forms.NumberInput(attrs={"class": INPUT_CLS, "placeholder": "if known"}),
            "age": forms.NumberInput(attrs={"class": INPUT_CLS, "placeholder": "used to estimate max HR"}),
        }


class GoalForm(forms.ModelForm):
    class Meta:
        model = Goal
        fields = ["title", "event_date", "target_distance_km", "notes"]
        widgets = {
            "title": forms.TextInput(attrs={"class": INPUT_CLS, "placeholder": "e.g. City Marathon"}),
            "event_date": forms.DateInput(attrs={"type": "date", "class": INPUT_CLS}),
            "target_distance_km": forms.NumberInput(attrs={"class": INPUT_CLS, "step": "0.1", "placeholder": "km, optional"}),
            "notes": forms.Textarea(attrs={"rows": 2, "class": INPUT_CLS}),
        }
