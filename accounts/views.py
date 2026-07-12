from django.contrib.auth import login
from django.contrib.auth.views import LoginView
from django.shortcuts import render, redirect
from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit

from .forms import SignupForm


@ratelimit(key="ip", rate="5/h", block=True)
def signup(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == "POST":
        form = SignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("dashboard")
    else:
        form = SignupForm()

    return render(request, "registration/signup.html", {"form": form})


@method_decorator(ratelimit(key="ip", rate="5/m", block=True), name="post")
class RateLimitedLoginView(LoginView):
    pass