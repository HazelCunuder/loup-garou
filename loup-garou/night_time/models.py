from django.db import models
from django.db.models import Q

from game.models import Game, Player, Role


class NightActionType(models.TextChoices):
    WOLF_TARGET = "WOLF_TARGET", "Cible du loup"
    SEER_INSPECT = "SEER_INSPECT", "Sondage de la voyante"
    WITCH_HEAL = "WITCH_HEAL", "Potion de vie"
    WITCH_KILL = "WITCH_KILL", "Potion de mort"
    # La sorcière choisit de ne rien faire : clôt son tour sans attendre le timer.
    WITCH_PASS = "WITCH_PASS", "La sorcière passe"


class NightAction(models.Model):
    """Une action nocturne d'un joueur.

    Chaque loup enregistre sa propre cible (le consensus est calculé à la
    résolution) ; la sorcière enregistre sa décision en une fois : soin et/ou
    poison, ou WITCH_PASS. Une absence de ligne signifie que le timer a expiré.
    """

    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="night_actions")
    night_number = models.PositiveSmallIntegerField()
    actor = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="night_actions")
    action_type = models.CharField(max_length=16, choices=NightActionType.choices)
    # Null uniquement pour WITCH_PASS.
    target = models.ForeignKey(
        Player,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="targeted_by_night_actions",
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
            models.CheckConstraint(
                condition=(
                    Q(action_type=NightActionType.WITCH_PASS, target__isnull=True)
                    | (
                        ~Q(action_type=NightActionType.WITCH_PASS)
                        & Q(target__isnull=False)
                    )
                ),
                name="night_action_target_unless_pass",
            ),
        ]

    def __str__(self):
        target = f" → {self.target.name}" if self.target_id else ""
        return f"Nuit {self.night_number} · {self.actor.name} → {self.get_action_type_display()}{target}"
