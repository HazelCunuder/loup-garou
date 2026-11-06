from django.test import TestCase

from game.engine import (
    InvalidAction,
    create_game,
    submit_message,
    submit_seer_inspection,
    submit_vote,
    submit_witch_decision,
    submit_wolf_target,
)
from game.engine.actions import MESSAGE_MAX_LENGTH
from game.models import Channel, GameStatus, Phase, Role, Winner
from night_time.models import NightAction, NightActionType as T
from voting.models import Vote

from .helpers import GameTestCase


class MessageActionTests(GameTestCase):
    def test_public_message_during_the_day(self):
        self.set_phase(Phase.DAY_DEBATE)
        msg = submit_message(self.game, self.human, "  Bonjour  ")
        self.assertEqual((msg.content, msg.channel, msg.phase), ("Bonjour", Channel.PUBLIC, Phase.DAY_DEBATE))

    def test_public_square_is_closed_at_night(self):
        with self.assertRaises(InvalidAction):
            submit_message(self.game, self.human, "Psst")

    def test_empty_or_too_long_message_is_rejected(self):
        self.set_phase(Phase.DAY_DEBATE)
        for text in ("", "   ", "x" * (MESSAGE_MAX_LENGTH + 1)):
            with self.subTest(length=len(text)), self.assertRaises(InvalidAction):
                submit_message(self.game, self.human, text)

    def test_dead_players_cannot_speak(self):
        self.set_phase(Phase.DAY_DEBATE)
        self.kill(self.villagers[0])
        with self.assertRaises(InvalidAction):
            submit_message(self.game, self.villagers[0], "Je reviens !")

    def test_wolves_channel_during_wolves_night(self):
        self.set_phase(Phase.NIGHT_WOLVES)
        msg = submit_message(self.game, self.wolves[0], "On prend qui ?", Channel.WOLVES)
        self.assertEqual(msg.channel, Channel.WOLVES)

    def test_wolves_channel_is_for_wolves_only(self):
        self.set_phase(Phase.NIGHT_WOLVES)
        with self.assertRaises(InvalidAction):
            submit_message(self.game, self.seer, "Je vous entends", Channel.WOLVES)

    def test_wolves_channel_closed_by_day(self):
        self.set_phase(Phase.DAY_DEBATE)
        with self.assertRaises(InvalidAction):
            submit_message(self.game, self.wolves[0], "Discret…", Channel.WOLVES)


class VoteActionTests(GameTestCase):
    def setUp(self):
        super().setUp()
        self.set_phase(Phase.DAY_VOTE)

    def test_vote_and_abstention(self):
        vote = submit_vote(self.game, self.villagers[0], self.wolves[0])
        self.assertEqual(vote.target, self.wolves[0])
        self.assertTrue(submit_vote(self.game, self.villagers[1], None).is_abstention)

    def test_vote_against_self_is_rejected(self):
        # Cadrage : tentative de vote sur soi-même → rejet 400.
        with self.assertRaises(InvalidAction):
            submit_vote(self.game, self.human, self.human)

    def test_vote_against_dead_player_is_rejected(self):
        self.kill(self.villagers[0])
        with self.assertRaises(InvalidAction):
            submit_vote(self.game, self.human if self.human.is_alive else self.seer, self.villagers[0])

    def test_unknown_target_is_rejected(self):
        other = create_game("s2", "Autre", seed=1).players.first()
        for target in (other, 999999):
            with self.subTest(target=target), self.assertRaises(InvalidAction):
                submit_vote(self.game, self.seer, target)

    def test_wolf_can_vote_against_wolf_by_day(self):
        # Cadrage : le jour, vote fratricide accepté (bluff).
        submit_vote(self.game, self.wolves[0], self.wolves[1])

    def test_only_one_vote_per_day(self):
        submit_vote(self.game, self.seer, self.wolves[0])
        with self.assertRaises(InvalidAction):
            submit_vote(self.game, self.seer, self.wolves[1])

    def test_vote_outside_vote_phase_is_rejected(self):
        self.set_phase(Phase.DAY_DEBATE)
        with self.assertRaises(InvalidAction):
            submit_vote(self.game, self.seer, self.wolves[0])

    def test_last_vote_closes_the_vote(self):
        target = self.villagers[0]
        for voter in self.players:
            if voter != target:
                submit_vote(self.game, voter, target)
        self.game.refresh_from_db()
        self.assertEqual(self.game.phase, Phase.DAY_VOTE)
        submit_vote(self.game, target, None)
        self.game.refresh_from_db()
        self.assertEqual(self.game.phase, Phase.VOTE_RESULT)
        target.refresh_from_db()
        self.assertFalse(target.is_alive)


class SeerActionTests(GameTestCase):
    def test_inspection_reveals_the_role_and_ends_the_turn(self):
        action = submit_seer_inspection(self.game, self.seer, self.wolves[0])
        self.assertEqual(action.revealed_role, Role.WEREWOLF)
        self.game.refresh_from_db()
        self.assertEqual(self.game.phase, Phase.NIGHT_WOLVES)

    def test_only_the_seer_inspects(self):
        with self.assertRaises(InvalidAction):
            submit_seer_inspection(self.game, self.witch, self.wolves[0])

    def test_seer_cannot_inspect_herself_or_the_dead(self):
        self.kill(self.villagers[0])
        for target in (self.seer, self.villagers[0]):
            with self.subTest(target=target.name), self.assertRaises(InvalidAction):
                submit_seer_inspection(self.game, self.seer, target)

    def test_one_inspection_per_night(self):
        NightAction.objects.create(
            game=self.game, night_number=1, actor=self.seer,
            action_type=T.SEER_INSPECT, target=self.wolves[0], revealed_role=Role.WEREWOLF,
        )
        with self.assertRaises(InvalidAction):
            submit_seer_inspection(self.game, self.seer, self.wolves[1])

    def test_wrong_phase(self):
        self.set_phase(Phase.NIGHT_WOLVES)
        with self.assertRaises(InvalidAction):
            submit_seer_inspection(self.game, self.seer, self.wolves[0])


class WolfActionTests(GameTestCase):
    def setUp(self):
        super().setUp()
        self.set_phase(Phase.NIGHT_WOLVES)

    def test_wolf_cannot_target_a_wolf_at_night(self):
        # Cadrage : la nuit, formellement bloqué (target not in wolves).
        with self.assertRaises(InvalidAction):
            submit_wolf_target(self.game, self.wolves[0], self.wolves[1])

    def test_only_wolves_choose_a_victim(self):
        with self.assertRaises(InvalidAction):
            submit_wolf_target(self.game, self.seer, self.villagers[0])

    def test_wolf_can_change_its_mind_while_waiting(self):
        submit_wolf_target(self.game, self.wolves[0], self.villagers[0])
        submit_wolf_target(self.game, self.wolves[0], self.villagers[1])
        action = NightAction.objects.get(actor=self.wolves[0], action_type=T.WOLF_TARGET)
        self.assertEqual(action.target, self.villagers[1])

    def test_turn_ends_when_both_wolves_chose(self):
        submit_wolf_target(self.game, self.wolves[0], self.villagers[0])
        self.game.refresh_from_db()
        self.assertEqual(self.game.phase, Phase.NIGHT_WOLVES)
        submit_wolf_target(self.game, self.wolves[1], self.villagers[0])
        self.game.refresh_from_db()
        self.assertEqual(self.game.phase, Phase.NIGHT_WITCH)


class HumanWolfTests(GameTestCase):
    human_role = Role.WEREWOLF

    def test_ai_partner_follows_the_human_choice(self):
        self.set_phase(Phase.NIGHT_WOLVES)
        partner = next(w for w in self.wolves if not w.is_human)
        submit_wolf_target(self.game, partner, self.villagers[0])
        submit_wolf_target(self.game, self.human, self.seer)
        targets = set(
            NightAction.objects.filter(action_type=T.WOLF_TARGET).values_list("target_id", flat=True)
        )
        self.assertEqual(targets, {self.seer.pk})
        self.game.refresh_from_db()
        self.assertEqual(self.game.phase, Phase.NIGHT_WITCH)


class WitchActionTests(GameTestCase):
    def setUp(self):
        super().setUp()
        self.victim = self.villagers[0]
        for wolf in self.wolves:
            NightAction.objects.create(
                game=self.game, night_number=1, actor=wolf,
                action_type=T.WOLF_TARGET, target=self.victim,
            )
        self.set_phase(Phase.NIGHT_WITCH)

    def decided_types(self):
        return set(NightAction.objects.filter(actor=self.witch).values_list("action_type", flat=True))

    def test_heal_the_victim(self):
        submit_witch_decision(self.game, self.witch, heal=True)
        self.assertEqual(self.decided_types(), {T.WITCH_HEAL})
        self.game.refresh_from_db()
        self.assertEqual(self.game.phase, Phase.DAWN)
        self.victim.refresh_from_db()
        self.assertTrue(self.victim.is_alive)

    def test_heal_and_kill_someone_else(self):
        submit_witch_decision(self.game, self.witch, heal=True, kill_target=self.wolves[0])
        self.assertEqual(self.decided_types(), {T.WITCH_HEAL, T.WITCH_KILL})

    def test_cannot_heal_and_kill_the_same_person(self):
        with self.assertRaises(InvalidAction):
            submit_witch_decision(self.game, self.witch, heal=True, kill_target=self.victim)

    def test_pass(self):
        submit_witch_decision(self.game, self.witch)
        self.assertEqual(self.decided_types(), {T.WITCH_PASS})
        self.game.refresh_from_db()
        self.assertEqual(self.game.phase, Phase.DAWN)

    def test_heal_without_victim_is_rejected(self):
        NightAction.objects.filter(action_type=T.WOLF_TARGET).delete()
        with self.assertRaises(InvalidAction):
            submit_witch_decision(self.game, self.witch, heal=True)

    def test_used_potions_are_rejected(self):
        self.witch.has_life_potion = self.witch.has_death_potion = False
        self.witch.save()
        with self.assertRaises(InvalidAction):
            submit_witch_decision(self.game, self.witch, heal=True)
        with self.assertRaises(InvalidAction):
            submit_witch_decision(self.game, self.witch, kill_target=self.wolves[0])

    def test_cannot_poison_herself(self):
        with self.assertRaises(InvalidAction):
            submit_witch_decision(self.game, self.witch, kill_target=self.witch)

    def test_single_decision_per_night(self):
        submit_witch_decision(self.game, self.witch, kill_target=self.wolves[0])
        self.set_phase(Phase.NIGHT_WITCH)
        with self.assertRaises(InvalidAction):
            submit_witch_decision(self.game, self.witch)

    def test_only_the_witch_uses_potions(self):
        with self.assertRaises(InvalidAction):
            submit_witch_decision(self.game, self.seer, heal=True)


class WitchSelfHealTests(GameTestCase):
    def test_targeted_witch_saves_herself(self):
        for wolf in self.wolves:
            NightAction.objects.create(
                game=self.game, night_number=1, actor=wolf,
                action_type=T.WOLF_TARGET, target=self.witch,
            )
        self.set_phase(Phase.NIGHT_WITCH)
        submit_witch_decision(self.game, self.witch, heal=True)
        self.witch.refresh_from_db()
        self.assertTrue(self.witch.is_alive)


class FinishedGameTests(GameTestCase):
    def test_no_action_after_the_end(self):
        self.set_phase(Phase.GAME_OVER, status=GameStatus.FINISHED, winner=Winner.VILLAGE)
        with self.assertRaises(InvalidAction):
            submit_message(self.game, self.human, "Encore ?")
