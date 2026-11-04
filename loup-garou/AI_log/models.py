from django.db import models
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce

from game.models import Game, Phase, Player


class CallType(models.TextChoices):
    CHAT = "CHAT", "Message de débat"
    VOTE = "VOTE", "Vote de jour"
    NIGHT_ACTION = "NIGHT_ACTION", "Action de nuit"


class CallStatus(models.TextChoices):
    OK = "OK", "Succès"
    TIMEOUT = "TIMEOUT", "Délai dépassé"
    ERROR = "ERROR", "Erreur"
    INVALID_OUTPUT = "INVALID_OUTPUT", "Sortie invalide"


class AICallLogQuerySet(models.QuerySet):
    def total_tokens(self):
        """Somme des tokens d'entrée et de sortie (0 si aucun appel)."""
        totals = self.aggregate(
            prompt=Coalesce(Sum("prompt_tokens"), 0),
            completion=Coalesce(Sum("completion_tokens"), 0),
        )
        return totals["prompt"] + totals["completion"]


class AICallLog(models.Model):
    """Journal d'un appel LLM : budget de tokens, latence et incidents."""

    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="ai_calls")
    player = models.ForeignKey(
        Player,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="ai_calls",
    )
    day_number = models.PositiveSmallIntegerField()
    phase = models.CharField(max_length=16, choices=Phase.choices)
    call_type = models.CharField(max_length=16, choices=CallType.choices)
    model_name = models.CharField(max_length=64)
    prompt_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=CallStatus.choices)
    used_fallback = models.BooleanField(default=False)
    error_message = models.TextField(blank=True, default="")
    raw_output = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AICallLogQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["game", "status"], name="ai_call_game_status_idx")]
        constraints = [
            # Toute défaillance déclenche le repli procédural.
            models.CheckConstraint(
                condition=Q(status=CallStatus.OK) | Q(used_fallback=True),
                name="ai_call_failure_uses_fallback",
            ),
        ]

    @property
    def total_tokens(self):
        return self.prompt_tokens + self.completion_tokens

    def __str__(self):
        return f"{self.get_call_type_display()} · {self.get_status_display()} · {self.total_tokens} tokens"
