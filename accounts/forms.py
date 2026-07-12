from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import User

INPUT_CLS = "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"


class SignupForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("email",)
        widgets = {
            "email": forms.EmailInput(attrs={"class": INPUT_CLS, "placeholder": "you@example.com", "autofocus": True}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password1"].widget.attrs.update({"class": INPUT_CLS})
        self.fields["password2"].widget.attrs.update({"class": INPUT_CLS})
        self.fields["password1"].help_text = "At least 8 characters, not too common or all-numeric."