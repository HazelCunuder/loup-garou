from django.db import models
from django.db.models import F, Q

from game.models import Game, Player


class Vote(models.Model):
    """Vote de jour. ``target`` null = vote blanc / abstention.

    Le rejet d'un vote contre un mort est une règle du moteur ; le vote contre
    soi-même est en plus interdit en base.
    """

    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="votes")
    day_number = models.PositiveSmallIntegerField()
    voter = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="votes_cast")
    target = models.ForeignKey(
        Player,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="votes_received",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["day_number", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["game", "day_number", "voter"], name="vote_once_per_day"
            ),
            models.CheckConstraint(
                condition=~Q(voter=F("target")), name="vote_not_against_self"
            ),
            models.CheckConstraint(
                condition=Q(day_number__gte=1), name="vote_day_number_gte_1"
            ),
        ]

    @property
    def is_abstention(self):
        return self.target_id is None

    def __str__(self):
        target = self.target.name if self.target_id else "abstention"
        return f"Jour {self.day_number} · {self.voter.name} → {target}"
