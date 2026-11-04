from datetime import timedelta
from unittest import mock

from django.db.models import F
from django.test import TestCase
from django.utils import timezone

from game.engine import PhaseConflict, advance, advance_if_expired, check_winner, create_game
from game.models import DeathCause, Game, GameStatus, Phase, Player, Role, Winner


class StateMachineTestCase(TestCase):
    def setUp(self):
        self.game = create_game("s", "Hazel", seed=7)

    def player(self, role):
        return self.game.players.filter(role=role).first()

    def kill(self, *players):
        for p in players:
            Player.objects.filter(pk=p.pk).update(
                is_alive=False, died_on_day=1, death_cause=DeathCause.VOTE
            )

    def set_phase(self, phase):
        Game.objects.filter(pk=self.game.pk).update(phase=phase)
        self.game.refresh_from_db()

    def run_phases(self, count):
        phases = []
        for _ in range(count):
            self.game = advance(self.game)
            phases.append(self.game.phase)
        return phases


class FullCycleTests(StateMachineTestCase):
    def test_full_cycle_order(self):
        self.assertEqual(
            self.run_phases(6),
            [
                Phase.NIGHT_WOLVES,
                Phase.NIGHT_WITCH,
                Phase.DAWN,
                Phase.DAY_DEBATE,
                Phase.DAY_VOTE,
                Phase.NIGHT_SEER,
            ],
        )

    def test_day_number_increments_when_night_falls(self):
        self.run_phases(5)
        self.assertEqual(self.game.day_number, 1)
        self.run_phases(1)
        self.assertEqual(self.game.day_number, 2)

    def test_each_transition_bumps_version_and_restarts_timer(self):
        before = self.game
        after = advance(before)
        self.assertEqual(after.version, before.version + 1)
        self.assertGreaterEqual(after.phase_started_at, before.phase_started_at)
        self.assertEqual(after.phase_deadline - after.phase_started_at, timedelta(seconds=45))

    def test_dawn_has_a_short_timer(self):
        self.set_phase(Phase.NIGHT_WITCH)
        game = advance(self.game)
        self.assertEqual(game.phase, Phase.DAWN)
        self.assertEqual(game.phase_deadline - game.phase_started_at, timedelta(seconds=8))


class SkippedPhaseTests(StateMachineTestCase):
    def test_dead_seer_phase_is_skipped(self):
        self.kill(self.player(Role.SEER))
        self.set_phase(Phase.DAY_VOTE)
        self.assertEqual(advance(self.game).phase, Phase.NIGHT_WOLVES)

    def test_dead_witch_phase_is_skipped(self):
        self.kill(self.player(Role.WITCH))
        self.set_phase(Phase.NIGHT_WOLVES)
        self.assertEqual(advance(self.game).phase, Phase.DAWN)

    def test_witch_without_potions_is_skipped(self):
        Player.objects.filter(game=self.game, role=Role.WITCH).update(
            has_life_potion=False, has_death_potion=False
        )
        self.set_phase(Phase.NIGHT_WOLVES)
        self.assertEqual(advance(self.game).phase, Phase.DAWN)

    def test_witch_with_one_potion_still_plays(self):
        Player.objects.filter(game=self.game, role=Role.WITCH).update(has_life_potion=False)
        self.set_phase(Phase.NIGHT_WOLVES)
        self.assertEqual(advance(self.game).phase, Phase.NIGHT_WITCH)

    def test_seer_and_witch_dead_night_is_wolves_only(self):
        self.kill(self.player(Role.SEER), self.player(Role.WITCH))
        self.set_phase(Phase.DAY_VOTE)
        self.assertEqual(self.run_phases(2), [Phase.NIGHT_WOLVES, Phase.DAWN])


class CheckWinnerTests(StateMachineTestCase):
    def players(self):
        return list(self.game.players.all())

    def test_no_winner_at_start(self):
        self.assertIsNone(check_winner(self.players()))

    def test_wolves_win_at_parity(self):
        self.kill(*self.game.players.exclude(role=Role.WEREWOLF)[:3])
        self.assertEqual(check_winner(self.players()), Winner.WOLVES)

    def test_no_winner_with_one_wolf_against_two(self):
        self.kill(self.player(Role.WEREWOLF))
        self.kill(*self.game.players.exclude(role=Role.WEREWOLF)[:3])
        self.assertIsNone(check_winner(self.players()))

    def test_village_wins_when_no_wolf_is_alive(self):
        self.kill(*self.game.players.filter(role=Role.WEREWOLF))
        self.assertEqual(check_winner(self.players()), Winner.VILLAGE)


class GameOverTests(StateMachineTestCase):
    def test_advance_ends_game_with_wolves_victory(self):
        self.kill(*self.game.players.exclude(role=Role.WEREWOLF)[:3])
        self.set_phase(Phase.DAY_VOTE)
        game = advance(self.game)
        self.assertEqual(game.phase, Phase.GAME_OVER)
        self.assertEqual(game.status, GameStatus.FINISHED)
        self.assertEqual(game.winner, Winner.WOLVES)
        self.assertIsNone(game.phase_deadline)

    def test_advance_ends_game_with_village_victory(self):
        self.kill(*self.game.players.filter(role=Role.WEREWOLF))
        game = advance(self.game)
        self.assertEqual((game.phase, game.winner), (Phase.GAME_OVER, Winner.VILLAGE))

    def test_finished_game_cannot_advance(self):
        self.kill(*self.game.players.filter(role=Role.WEREWOLF))
        game = advance(self.game)
        with self.assertRaises(PhaseConflict):
            advance(game)


class ConcurrencyTests(StateMachineTestCase):
    def test_stale_expected_phase_is_rejected(self):
        stale = Game.objects.get(pk=self.game.pk)
        advance(self.game, expected_phase=Phase.NIGHT_SEER)
        with self.assertRaises(PhaseConflict):
            advance(stale, expected_phase=stale.phase)
        self.game.refresh_from_db()
        self.assertEqual(self.game.phase, Phase.NIGHT_WOLVES)

    def test_concurrent_write_during_transition_is_rolled_back(self):
        self.set_phase(Phase.NIGHT_WITCH)
        victim = self.player(Role.VILLAGER)

        def concurrent_resolution(game):
            # Une résolution tue un joueur, mais un autre writer fait avancer
            # la partie en même temps : tout doit être annulé.
            Player.objects.filter(pk=victim.pk).update(
                is_alive=False, died_on_day=1, death_cause=DeathCause.WOLVES
            )
            Game.objects.filter(pk=game.pk).update(version=F("version") + 1)
            return [victim]

        with mock.patch("game.engine.resolution.resolve_night", side_effect=concurrent_resolution):
            with self.assertRaises(PhaseConflict):
                advance(self.game)

        self.game.refresh_from_db()
        victim.refresh_from_db()
        self.assertEqual(self.game.phase, Phase.NIGHT_WITCH)
        self.assertTrue(victim.is_alive)


class ResolutionHookTests(StateMachineTestCase):
    @mock.patch("game.engine.resolution.resolve_night", return_value=[])
    def test_night_is_resolved_when_dawn_comes(self, resolve_night):
        self.run_phases(2)
        resolve_night.assert_not_called()
        self.run_phases(1)
        resolve_night.assert_called_once()

    @mock.patch("game.engine.resolution.resolve_vote", return_value=None)
    def test_vote_is_resolved_when_leaving_day_vote(self, resolve_vote):
        self.run_phases(5)
        resolve_vote.assert_not_called()
        self.run_phases(1)
        resolve_vote.assert_called_once()

    def test_vote_victim_is_counted_before_next_night(self):
        seer = self.player(Role.SEER)
        self.set_phase(Phase.DAY_VOTE)
        with mock.patch(
            "game.engine.resolution.resolve_vote",
            side_effect=lambda game: self.kill(seer),
        ):
            self.assertEqual(advance(self.game).phase, Phase.NIGHT_WOLVES)


class TimerTests(StateMachineTestCase):
    def test_does_not_advance_before_deadline(self):
        self.assertFalse(advance_if_expired(self.game, now=timezone.now()))
        self.game.refresh_from_db()
        self.assertEqual(self.game.phase, Phase.NIGHT_SEER)

    def test_advances_after_deadline(self):
        later = self.game.phase_deadline + timedelta(seconds=1)
        self.assertTrue(advance_if_expired(self.game, now=later))
        self.game.refresh_from_db()
        self.assertEqual(self.game.phase, Phase.NIGHT_WOLVES)

    def test_expired_but_already_advanced_is_a_no_op(self):
        stale = Game.objects.get(pk=self.game.pk)
        advance(self.game)
        later = stale.phase_deadline + timedelta(seconds=1)
        self.assertFalse(advance_if_expired(stale, now=later))
        self.game.refresh_from_db()
        self.assertEqual(self.game.phase, Phase.NIGHT_WOLVES)
