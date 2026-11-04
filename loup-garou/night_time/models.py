from django.db import models
from django.db.models import Q

from game.models import Game, Player, Role


class NightActionType(models.TextChoices):
    WOLF_TARGET = "WOLF_TARGET", "Cible du loup"
    SEER_INSPECT = "SEER_INSPECT", "Sondage de la voyante"
    WITCH_HEAL = "WITCH_HEAL", "Potion de vie"
    WITCH_KILL = "WITCH_KILL", "Potion de mort"


class NightAction(models.Model):
    """Une action nocturne d'un joueur.

    Chaque loup enregistre sa propre cible (le consensus est calculé à la
    résolution) ; la sorcière peut avoir 0, 1 ou 2 lignes par nuit. Une absence
    de ligne signifie « aucune action » (timer expiré ou choix de passer).
    """

    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="night_actions")
    night_number = models.PositiveSmallIntegerField()
    actor = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="night_actions")
    action_type = models.CharField(max_length=16, choices=NightActionType.choices)
    target = models.ForeignKey(
        Player, on_delete=models.CASCADE, related_name="targeted_by_night_actions"
    )
    # Rôle révélé à la voyante : constitue son historique privé.
    revealed_role = models.CharField(
        max_length=16, choices=Role.choices, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["night_number", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["game", "night_number", "actor", "action_type"],
                name="night_action_once_per_night",
            ),
            models.CheckConstraint(
                condition=Q(night_number__gte=1),
                name="night_action_night_number_gte_1",
            ),
            models.CheckConstraint(
                condition=(
                    Q(action_type=NightActionType.SEER_INSPECT, revealed_role__isnull=False)
                    | (
                        ~Q(action_type=NightActionType.SEER_INSPECT)
                        & Q(revealed_role__isnull=True)
                    )
                ),
                name="night_action_revealed_role_only_for_seer",
            ),
        ]

    def __str__(self):
        return f"Nuit {self.night_number} · {self.actor.name} → {self.get_action_type_display()} → {self.target.name}"
