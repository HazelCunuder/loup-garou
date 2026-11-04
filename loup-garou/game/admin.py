from django.contrib import admin

from .models import Game, Player


class PlayerInline(admin.TabularInline):
    model = Player
    extra = 0
    fields = (
        "seat",
        "name",
        "is_human",
        "role",
        "personality",
        "is_alive",
        "died_on_day",
        "death_cause",
        "has_life_potion",
        "has_death_potion",
    )


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "phase", "day_number", "winner", "created_at")
    list_filter = ("status", "phase", "winner")
    search_fields = ("id", "session_key")
    readonly_fields = ("id", "seed", "version", "created_at", "updated_at")
    inlines = [PlayerInline]


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ("name", "game", "seat", "is_human", "role", "personality", "is_alive")
    list_filter = ("role", "personality", "is_human", "is_alive")
    search_fields = ("name", "game__id")
