from django.contrib import admin
from django.urls import path, include

from accounts import views as account_views
from accounts.views import RateLimitedLoginView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/signup/", account_views.signup, name="signup"),
    path("accounts/login/", RateLimitedLoginView.as_view(), name="login"),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("coach.urls")),
]