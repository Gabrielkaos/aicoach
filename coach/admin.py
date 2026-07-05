from django.contrib import admin
from .models import DailyMetric, Activity, Workout, ChatMessage, StravaToken

admin.site.register(DailyMetric)
admin.site.register(Activity)
admin.site.register(Workout)
admin.site.register(ChatMessage)
admin.site.register(StravaToken)
