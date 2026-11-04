from django.contrib import admin

from .models import Game


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "phase", "day_number", "winner", "created_at")
    list_filter = ("status", "phase", "winner")
    search_fields = ("id", "session_key")
    readonly_fields = ("id", "seed", "version", "created_at", "updated_at")
