from django.contrib import admin

from .models import AICallLog


@admin.register(AICallLog)
class AICallLogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "game",
        "player",
        "call_type",
        "status",
        "used_fallback",
        "prompt_tokens",
        "completion_tokens",
        "latency_ms",
    )
    list_filter = ("status", "call_type", "used_fallback")
    search_fields = ("game__id", "error_message")
