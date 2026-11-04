from django.contrib import admin

from .models import NightAction


@admin.register(NightAction)
class NightActionAdmin(admin.ModelAdmin):
    list_display = ("game", "night_number", "actor", "action_type", "target", "revealed_role")
    list_filter = ("action_type",)
    search_fields = ("game__id", "actor__name", "target__name")
