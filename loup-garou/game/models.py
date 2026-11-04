import random
import uuid

from django.db import models
from django.db.models import Q
from django.utils import timezone


class Phase(models.TextChoices):
    """Phases du cycle de jeu, dans l'ordre où la state machine les parcourt."""

    NIGHT_SEER = "NIGHT_SEER", "Nuit · voyante"
    NIGHT_WOLVES = "NIGHT_WOLVES", "Nuit · loups"
    NIGHT_WITCH = "NIGHT_WITCH", "Nuit · sorcière"
    DAWN = "DAWN", "Aube"
    DAY_DEBATE = "DAY_DEBATE", "Jour · débat"
    DAY_VOTE = "DAY_VOTE", "Jour · vote"
    GAME_OVER = "GAME_OVER", "Fin de partie"


class GameStatus(models.TextChoices):
    IN_PROGRESS = "IN_PROGRESS", "En cours"
    FINISHED = "FINISHED", "Terminée"


class Winner(models.TextChoices):
    WOLVES = "WOLVES", "Loups-Garous"
    VILLAGE = "VILLAGE", "Village"


def new_seed():
    """Graine aléatoire stockée avec la partie pour rejouer un tirage à l'identique."""
    return random.getrandbits(62)


class Game(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    status = models.CharField(
        max_length=16, choices=GameStatus.choices, default=GameStatus.IN_PROGRESS
    )
    # La première nuit commence par la voyante.
    phase = models.CharField(
        max_length=16, choices=Phase.choices, default=Phase.NIGHT_SEER
    )
    # Numéro du cycle nuit + jour en cours ; commence à 1.
    day_number = models.PositiveSmallIntegerField(default=1)
    phase_started_at = models.DateTimeField(default=timezone.now)
    # Échéance du timer de 45 s ; null pour les phases sans action attendue.
    phase_deadline = models.DateTimeField(null=True, blank=True)
    winner = models.CharField(
        max_length=8, choices=Winner.choices, null=True, blank=True
    )
    # Identifie le joueur humain sans compte utilisateur (MVP).
    session_key = models.CharField(max_length=64, db_index=True)
    seed = models.BigIntegerField(default=new_seed)
    # Verrou optimiste : incrémenté à chaque transition de phase.
    version = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # Une partie terminée est en GAME_OVER avec un vainqueur ;
            # une partie en cours n'a ni vainqueur ni phase GAME_OVER.
            models.CheckConstraint(
                condition=(
                    Q(
                        status=GameStatus.FINISHED,
                        phase=Phase.GAME_OVER,
                        winner__isnull=False,
                    )
                    | (
                        Q(status=GameStatus.IN_PROGRESS, winner__isnull=True)
                        & ~Q(phase=Phase.GAME_OVER)
                    )
                ),
                name="game_status_phase_winner_consistent",
            ),
            models.CheckConstraint(
                condition=Q(day_number__gte=1),
                name="game_day_number_gte_1",
            ),
        ]

    def __str__(self):
        return f"Partie {str(self.id)[:8]} · jour {self.day_number} · {self.get_phase_display()}"

    @property
    def is_finished(self):
        return self.status == GameStatus.FINISHED

    def is_expired(self, now=None):
        """Vrai si la phase a un timer et que son échéance est dépassée."""
        if self.phase_deadline is None:
            return False
        return (now or timezone.now()) >= self.phase_deadline
