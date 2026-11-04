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


class Role(models.TextChoices):
    WEREWOLF = "WEREWOLF", "Loup-Garou"
    VILLAGER = "VILLAGER", "Villageois"
    SEER = "SEER", "Voyante"
    WITCH = "WITCH", "Sorcière"


class Personality(models.TextChoices):
    STRATEGE = "STRATEGE", "Le Stratège"
    MAUVAISE_JOUEUSE = "MAUVAISE_JOUEUSE", "La Mauvaise Joueuse"
    CYNIQUE = "CYNIQUE", "Le Cynique"
    PARANOIAQUE = "PARANOIAQUE", "La Paranoïaque"
    DIPLOMATE = "DIPLOMATE", "La Diplomate"
    IMPULSIF = "IMPULSIF", "L'Impulsif"


class DeathCause(models.TextChoices):
    WOLVES = "WOLVES", "Dévoré par les loups"
    WITCH = "WITCH", "Empoisonné par la sorcière"
    VOTE = "VOTE", "Éliminé par le village"


class Player(models.Model):
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="players")
    seat = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=32)
    is_human = models.BooleanField(default=False)
    role = models.CharField(max_length=16, choices=Role.choices)
    # Null pour l'humain, obligatoire pour une IA.
    personality = models.CharField(
        max_length=20, choices=Personality.choices, null=True, blank=True
    )
    is_alive = models.BooleanField(default=True)
    died_on_day = models.PositiveSmallIntegerField(null=True, blank=True)
    death_cause = models.CharField(
        max_length=8, choices=DeathCause.choices, null=True, blank=True
    )
    # Potions à usage unique ; uniquement possibles pour la sorcière.
    has_life_potion = models.BooleanField(default=False)
    has_death_potion = models.BooleanField(default=False)
    # Mémoire privée de l'IA : pensée interne de son tour précédent.
    last_thought = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["game", "seat"]
        constraints = [
            models.UniqueConstraint(fields=["game", "seat"], name="player_unique_seat"),
            models.UniqueConstraint(fields=["game", "name"], name="player_unique_name"),
            models.UniqueConstraint(
                fields=["game"],
                condition=Q(is_human=True),
                name="player_single_human_per_game",
            ),
            models.CheckConstraint(
                condition=(
                    Q(is_human=True, personality__isnull=True)
                    | Q(is_human=False, personality__isnull=False)
                ),
                name="player_personality_only_for_ai",
            ),
            models.CheckConstraint(
                condition=(
                    Q(role=Role.WITCH)
                    | Q(has_life_potion=False, has_death_potion=False)
                ),
                name="player_potions_only_for_witch",
            ),
            models.CheckConstraint(
                condition=(
                    Q(is_alive=True, died_on_day__isnull=True, death_cause__isnull=True)
                    | Q(is_alive=False, died_on_day__isnull=False, death_cause__isnull=False)
                ),
                name="player_death_fields_consistent",
            ),
        ]

    def __str__(self):
        return f"{self.name} (siège {self.seat})"

    @property
    def is_wolf(self):
        return self.role == Role.WEREWOLF


class Channel(models.TextChoices):
    PUBLIC = "PUBLIC", "Place du village"
    WOLVES = "WOLVES", "Canal secret des loups"


class MessageKind(models.TextChoices):
    CHAT = "CHAT", "Message de joueur"
    ANNOUNCEMENT = "ANNOUNCEMENT", "Annonce du Maître du Jeu"


class Message(models.Model):
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="messages")
    # Null pour une annonce du Maître du Jeu.
    author = models.ForeignKey(
        Player,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="messages",
    )
    channel = models.CharField(
        max_length=8, choices=Channel.choices, default=Channel.PUBLIC
    )
    kind = models.CharField(
        max_length=16, choices=MessageKind.choices, default=MessageKind.CHAT
    )
    # Texte brut : les chevrons sont neutralisés au moment de l'injection dans
    # un prompt (côté IA) et par l'échappement automatique des templates.
    content = models.TextField()
    day_number = models.PositiveSmallIntegerField()
    phase = models.CharField(max_length=16, choices=Phase.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # L'id croissant sert de curseur au polling (« messages après l'id N »).
        ordering = ["id"]
        indexes = [
            models.Index(fields=["game", "channel", "id"], name="message_polling_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(kind=MessageKind.CHAT, author__isnull=False)
                    | Q(kind=MessageKind.ANNOUNCEMENT, author__isnull=True)
                ),
                name="message_author_matches_kind",
            ),
            models.CheckConstraint(
                condition=~Q(content=""),
                name="message_content_not_empty",
            ),
        ]

    def __str__(self):
        who = self.author.name if self.author_id else "MJ"
        return f"[{self.channel}] {who} : {self.content[:40]}"
