from datetime import timedelta

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from game.models import Game, GameStatus, Phase, Winner


class GameDefaultsTests(TestCase):
    def test_new_game_starts_on_first_night_with_seer(self):
        game = Game.objects.create(session_key="s1")

        self.assertEqual(game.status, GameStatus.IN_PROGRESS)
        self.assertEqual(game.phase, Phase.NIGHT_SEER)
        self.assertEqual(game.day_number, 1)
        self.assertEqual(game.version, 0)
        self.assertIsNone(game.winner)
        self.assertIsNone(game.phase_deadline)
        self.assertFalse(game.is_finished)

    def test_night_order_is_seer_then_wolves_then_witch(self):
        phases = list(Phase.values)
        self.assertLess(phases.index(Phase.NIGHT_SEER), phases.index(Phase.NIGHT_WOLVES))
        self.assertLess(phases.index(Phase.NIGHT_WOLVES), phases.index(Phase.NIGHT_WITCH))

    def test_each_game_gets_its_own_uuid_and_seed(self):
        a = Game.objects.create(session_key="s1")
        b = Game.objects.create(session_key="s1")

        self.assertNotEqual(a.pk, b.pk)
        self.assertIsNotNone(a.seed)
        self.assertNotEqual(a.seed, b.seed)

    def test_explicit_seed_is_persisted(self):
        game = Game.objects.create(session_key="s1", seed=42)
        game.refresh_from_db()
        self.assertEqual(game.seed, 42)


class GameTimerTests(TestCase):
    def test_no_deadline_never_expires(self):
        game = Game(session_key="s1")
        self.assertFalse(game.is_expired())

    def test_expires_at_or_after_deadline(self):
        now = timezone.now()
        game = Game(session_key="s1", phase_deadline=now + timedelta(seconds=45))

        self.assertFalse(game.is_expired(now))
        self.assertTrue(game.is_expired(now + timedelta(seconds=45)))
        self.assertTrue(game.is_expired(now + timedelta(seconds=60)))


class GameConstraintTests(TestCase):
    def assertRejected(self, **fields):
        with transaction.atomic(), self.assertRaises(IntegrityError):
            Game.objects.create(session_key="s1", **fields)

    def test_finished_game_with_winner_in_game_over_is_valid(self):
        game = Game.objects.create(
            session_key="s1",
            status=GameStatus.FINISHED,
            phase=Phase.GAME_OVER,
            winner=Winner.WOLVES,
        )
        self.assertTrue(game.is_finished)

    def test_winner_on_game_in_progress_is_rejected(self):
        self.assertRejected(winner=Winner.VILLAGE)

    def test_finished_game_without_winner_is_rejected(self):
        self.assertRejected(status=GameStatus.FINISHED, phase=Phase.GAME_OVER)

    def test_finished_game_outside_game_over_is_rejected(self):
        self.assertRejected(
            status=GameStatus.FINISHED, phase=Phase.DAY_VOTE, winner=Winner.WOLVES
        )

    def test_game_over_phase_while_in_progress_is_rejected(self):
        self.assertRejected(phase=Phase.GAME_OVER)

    def test_day_number_zero_is_rejected(self):
        self.assertRejected(day_number=0)
