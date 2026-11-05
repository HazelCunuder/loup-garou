from django.test import TestCase

from game.engine import create_game
from game.models import DeathCause, Game, MessageKind, Player, Role


class GameTestCase(TestCase):
    """Partie à 7 joueurs prête à l'emploi, avec accès aux joueurs par rôle."""

    human_role = None
    seed = 7

    def setUp(self):
        self.game = create_game("s", "Alexandre", seed=self.seed, human_role=self.human_role)
        self.refresh()

    def refresh(self):
        self.game.refresh_from_db()
        players = list(self.game.players.all())
        self.human = next(p for p in players if p.is_human)
        self.wolves = [p for p in players if p.role == Role.WEREWOLF]
        self.villagers = [p for p in players if p.role == Role.VILLAGER]
        self.seer = next(p for p in players if p.role == Role.SEER)
        self.witch = next(p for p in players if p.role == Role.WITCH)
        self.non_wolves = [p for p in players if p.role != Role.WEREWOLF]
        self.players = players

    def set_phase(self, phase, **fields):
        Game.objects.filter(pk=self.game.pk).update(phase=phase, **fields)
        self.game.refresh_from_db()

    def kill(self, *players):
        for p in players:
            Player.objects.filter(pk=p.pk).update(
                is_alive=False, died_on_day=1, death_cause=DeathCause.VOTE
            )
        self.refresh()

    def announcements(self):
        return list(
            self.game.messages.filter(kind=MessageKind.ANNOUNCEMENT).values_list("content", flat=True)
        )

    def last_announcement(self):
        return self.announcements()[-1]
