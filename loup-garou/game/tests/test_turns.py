from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from game.engine import create_game, expected_actors, is_phase_complete, pending_actors, try_advance
from game.models import DeathCause, Game, Phase, Player, Role
from night_time.models import NightAction, NightActionType
from voting.models import Vote


class TurnsTestCase(TestCase):
    def setUp(self):
        self.game = create_game("s", "Hazel", seed=7)
        self.seer = self.game.players.get(role=Role.SEER)
        self.witch = self.game.players.get(role=Role.WITCH)
        self.wolves = list(self.game.players.filter(role=Role.WEREWOLF))
        self.villagers = list(self.game.players.filter(role=Role.VILLAGER))

    def set_phase(self, phase):
        Game.objects.filter(pk=self.game.pk).update(phase=phase)
        self.game.refresh_from_db()

    def kill(self, player):
        Player.objects.filter(pk=player.pk).update(
            is_alive=False, died_on_day=1, death_cause=DeathCause.VOTE
        )

    def night_action(self, actor, action_type, target=None, **fields):
        return NightAction.objects.create(
            game=self.game, night_number=self.game.day_number, actor=actor,
            action_type=action_type, target=target, **fields,
        )

    def vote(self, voter, target):
        return Vote.objects.create(
            game=self.game, day_number=self.game.day_number, voter=voter, target=target
        )

    def assertAdvancesTo(self, phase):
        self.assertTrue(try_advance(self.game))
        self.game.refresh_from_db()
        self.assertEqual(self.game.phase, phase)

    def assertWaits(self):
        before = self.game.phase
        self.assertFalse(try_advance(self.game))
        self.game.refresh_from_db()
        self.assertEqual(self.game.phase, before)


class ExpectedActorsTests(TurnsTestCase):
    def test_night_phases_expect_their_role(self):
        cases = {
            Phase.NIGHT_SEER: [self.seer],
            Phase.NIGHT_WOLVES: self.wolves,
            Phase.NIGHT_WITCH: [self.witch],
        }
        for phase, actors in cases.items():
            with self.subTest(phase=phase):
                self.set_phase(phase)
                self.assertEqual(expected_actors(self.game), actors)

    def test_day_vote_expects_every_living_player(self):
        self.kill(self.villagers[0])
        self.set_phase(Phase.DAY_VOTE)
        self.assertEqual(len(expected_actors(self.game)), 6)
        self.assertNotIn(self.villagers[0], expected_actors(self.game))

    def test_display_and_debate_phases_expect_nobody(self):
        for phase in (Phase.DAWN, Phase.DAY_DEBATE, Phase.VOTE_RESULT):
            with self.subTest(phase=phase):
                self.set_phase(phase)
                self.assertEqual(expected_actors(self.game), [])
                self.assertFalse(is_phase_complete(self.game))

    def test_dead_wolf_is_not_expected(self):
        self.kill(self.wolves[0])
        self.set_phase(Phase.NIGHT_WOLVES)
        self.assertEqual(expected_actors(self.game), [self.wolves[1]])


class NightTurnTests(TurnsTestCase):
    def test_seer_turn_ends_when_she_inspects(self):
        self.assertWaits()
        self.night_action(
            self.seer, NightActionType.SEER_INSPECT, self.wolves[0], revealed_role=Role.WEREWOLF
        )
        self.assertAdvancesTo(Phase.NIGHT_WOLVES)

    def test_wolves_turn_waits_for_every_wolf(self):
        self.set_phase(Phase.NIGHT_WOLVES)
        self.night_action(self.wolves[0], NightActionType.WOLF_TARGET, self.villagers[0])
        self.assertEqual(pending_actors(self.game), [self.wolves[1]])
        self.assertWaits()
        self.night_action(self.wolves[1], NightActionType.WOLF_TARGET, self.villagers[0])
        self.assertAdvancesTo(Phase.NIGHT_WITCH)

    def test_lone_wolf_closes_the_turn_alone(self):
        self.kill(self.wolves[0])
        self.set_phase(Phase.NIGHT_WOLVES)
        self.night_action(self.wolves[1], NightActionType.WOLF_TARGET, self.villagers[0])
        self.assertAdvancesTo(Phase.NIGHT_WITCH)

    def test_witch_turn_ends_on_any_decision(self):
        decisions = [
            [(NightActionType.WITCH_HEAL, "villager")],
            [(NightActionType.WITCH_KILL, "wolf")],
            [(NightActionType.WITCH_HEAL, "villager"), (NightActionType.WITCH_KILL, "wolf")],
            [(NightActionType.WITCH_PASS, None)],
        ]
        targets = {"villager": self.villagers[0], "wolf": self.wolves[0], None: None}
        for decision in decisions:
            with self.subTest(decision=decision):
                NightAction.objects.filter(game=self.game).delete()
                self.set_phase(Phase.NIGHT_WITCH)
                for action_type, target in decision:
                    self.night_action(self.witch, action_type, targets[target])
                self.assertAdvancesTo(Phase.DAWN)

    def test_actions_from_a_previous_night_do_not_count(self):
        NightAction.objects.create(
            game=self.game, night_number=1, actor=self.seer,
            action_type=NightActionType.SEER_INSPECT, target=self.wolves[0],
            revealed_role=Role.WEREWOLF,
        )
        Game.objects.filter(pk=self.game.pk).update(day_number=2)
        self.game.refresh_from_db()
        self.assertWaits()


class DayTurnTests(TurnsTestCase):
    def test_vote_ends_when_every_living_player_voted(self):
        self.set_phase(Phase.DAY_VOTE)
        players = list(self.game.players.all())
        for voter in players[:-1]:
            self.vote(voter, None if voter == players[0] else players[0])
        self.assertWaits()
        self.vote(players[-1], None)
        self.assertAdvancesTo(Phase.VOTE_RESULT)

    def test_debate_only_ends_on_timer(self):
        self.set_phase(Phase.DAY_DEBATE)
        Game.objects.filter(pk=self.game.pk).update(phase_deadline=timezone.now() + timedelta(seconds=45))
        self.game.refresh_from_db()
        self.assertWaits()
        self.assertTrue(try_advance(self.game, now=self.game.phase_deadline))
        self.game.refresh_from_db()
        self.assertEqual(self.game.phase, Phase.DAY_VOTE)


class TryAdvanceTests(TurnsTestCase):
    def test_timer_closes_an_incomplete_turn(self):
        later = self.game.phase_deadline + timedelta(seconds=1)
        self.assertTrue(try_advance(self.game, now=later))

    def test_second_concurrent_call_is_a_no_op(self):
        self.night_action(
            self.seer, NightActionType.SEER_INSPECT, self.wolves[0], revealed_role=Role.WEREWOLF
        )
        stale = Game.objects.get(pk=self.game.pk)
        self.assertTrue(try_advance(self.game))
        self.assertFalse(try_advance(stale))
        self.game.refresh_from_db()
        self.assertEqual(self.game.phase, Phase.NIGHT_WOLVES)

    def test_finished_game_never_advances(self):
        for wolf in self.wolves:
            self.kill(wolf)
        self.assertTrue(try_advance(self.game, now=self.game.phase_deadline))
        self.game.refresh_from_db()
        self.assertEqual(self.game.phase, Phase.GAME_OVER)
        self.assertFalse(try_advance(self.game, now=timezone.now() + timedelta(days=1)))
