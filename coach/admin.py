from django.contrib import admin
from .models import DailyMetric, ActiveCondition, Workout, ChatMessage, ChatSession, AthleteProfile, Goal

admin.site.register(DailyMetric)
admin.site.register(ActiveCondition)
admin.site.register(Workout)
admin.site.register(ChatMessage)
admin.site.register(ChatSession)
admin.site.register(AthleteProfile)
admin.site.register(Goal)
