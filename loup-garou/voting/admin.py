from django.contrib import admin

from .models import Vote


@admin.register(Vote)
class VoteAdmin(admin.ModelAdmin):
    list_display = ("game", "day_number", "voter", "target")
    search_fields = ("game__id", "voter__name", "target__name")
