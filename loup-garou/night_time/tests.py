from django.db import IntegrityError, transaction
from django.test import TestCase

from game.models import Game, Personality, Player, Role
from night_time.models import NightAction, NightActionType


class NightActionModelTests(TestCase):
    def setUp(self):
        self.game = Game.objects.create(session_key="s1")
        self.wolf = self.add_player(0, "Loup", Role.WEREWOLF)
        self.seer = self.add_player(1, "Voyante", Role.SEER)
        self.witch = self.add_player(2, "Sorcière", Role.WITCH)
        self.villager = self.add_player(3, "Villageois", Role.VILLAGER)

    def add_player(self, seat, name, role):
        return Player.objects.create(
            game=self.game, seat=seat, name=name, role=role,
            personality=Personality.DIPLOMATE,
        )

    def act(self, actor, action_type, target, night=1, **fields):
        return NightAction.objects.create(
            game=self.game, night_number=night, actor=actor,
            action_type=action_type, target=target, **fields,
        )

    def assertRejected(self, *args, **fields):
        with transaction.atomic(), self.assertRaises(IntegrityError):
            self.act(*args, **fields)

    def test_wolf_target(self):
        action = self.act(self.wolf, NightActionType.WOLF_TARGET, self.villager)
        self.assertEqual(self.villager.targeted_by_night_actions.get(), action)

    def test_seer_inspect_stores_revealed_role(self):
        action = self.act(
            self.seer, NightActionType.SEER_INSPECT, self.wolf, revealed_role=Role.WEREWOLF
        )
        self.assertEqual(action.revealed_role, Role.WEREWOLF)

    def test_seer_inspect_without_revealed_role_is_rejected(self):
        self.assertRejected(self.seer, NightActionType.SEER_INSPECT, self.wolf)

    def test_revealed_role_on_other_action_is_rejected(self):
        self.assertRejected(
            self.wolf, NightActionType.WOLF_TARGET, self.seer, revealed_role=Role.SEER
        )

    def test_witch_can_heal_and_kill_the_same_night(self):
        self.act(self.witch, NightActionType.WITCH_HEAL, self.villager)
        self.act(self.witch, NightActionType.WITCH_KILL, self.wolf)
        self.assertEqual(self.witch.night_actions.count(), 2)

    def test_same_action_twice_in_one_night_is_rejected(self):
        self.act(self.wolf, NightActionType.WOLF_TARGET, self.villager)
        self.assertRejected(self.wolf, NightActionType.WOLF_TARGET, self.seer)

    def test_same_action_allowed_on_another_night(self):
        self.act(self.wolf, NightActionType.WOLF_TARGET, self.villager, night=1)
        self.act(self.wolf, NightActionType.WOLF_TARGET, self.seer, night=2)

    def test_night_zero_is_rejected(self):
        self.assertRejected(self.wolf, NightActionType.WOLF_TARGET, self.seer, night=0)
