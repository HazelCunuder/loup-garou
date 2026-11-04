from django.db import IntegrityError, transaction
from django.test import TestCase

from game.models import DeathCause, Game, Personality, Player, Role


class PlayerTestCase(TestCase):
    def setUp(self):
        self.game = Game.objects.create(session_key="s1")

    def make_player(self, seat=0, name=None, **fields):
        fields.setdefault("role", Role.VILLAGER)
        if not fields.get("is_human"):
            fields.setdefault("personality", Personality.STRATEGE)
        return Player.objects.create(
            game=fields.pop("game", self.game),
            seat=seat,
            name=name or f"Joueur{seat}",
            **fields,
        )

    def assertRejected(self, **fields):
        with transaction.atomic(), self.assertRaises(IntegrityError):
            self.make_player(**fields)


class PlayerDefaultsTests(PlayerTestCase):
    def test_new_player_is_alive_without_potions_or_thought(self):
        player = self.make_player()

        self.assertTrue(player.is_alive)
        self.assertIsNone(player.died_on_day)
        self.assertIsNone(player.death_cause)
        self.assertFalse(player.has_life_potion)
        self.assertFalse(player.has_death_potion)
        self.assertEqual(player.last_thought, "")

    def test_is_wolf(self):
        wolf = self.make_player(seat=0, role=Role.WEREWOLF)
        seer = self.make_player(seat=1, role=Role.SEER)

        self.assertTrue(wolf.is_wolf)
        self.assertFalse(seer.is_wolf)

    def test_players_are_listed_by_seat(self):
        self.make_player(seat=2)
        self.make_player(seat=0)
        self.make_player(seat=1)

        self.assertEqual([p.seat for p in self.game.players.all()], [0, 1, 2])

    def test_deleting_game_deletes_its_players(self):
        self.make_player()
        self.game.delete()
        self.assertFalse(Player.objects.exists())


class PlayerUniquenessTests(PlayerTestCase):
    def test_two_players_cannot_share_a_seat(self):
        self.make_player(seat=0, name="A")
        self.assertRejected(seat=0, name="B")

    def test_two_players_cannot_share_a_name(self):
        self.make_player(seat=0, name="Alice")
        self.assertRejected(seat=1, name="Alice")

    def test_same_seat_and_name_allowed_in_another_game(self):
        self.make_player(seat=0, name="Alice")
        other = Game.objects.create(session_key="s2")
        self.make_player(seat=0, name="Alice", game=other)

    def test_only_one_human_per_game(self):
        self.make_player(seat=0, is_human=True)
        self.assertRejected(seat=1, is_human=True)

    def test_several_ai_players_allowed(self):
        self.make_player(seat=0)
        self.make_player(seat=1)
        self.assertEqual(self.game.players.count(), 2)


class PlayerPersonalityTests(PlayerTestCase):
    def test_human_has_no_personality(self):
        human = self.make_player(is_human=True)
        self.assertIsNone(human.personality)

    def test_human_with_personality_is_rejected(self):
        self.assertRejected(is_human=True, personality=Personality.CYNIQUE)

    def test_ai_without_personality_is_rejected(self):
        self.assertRejected(personality=None)


class PlayerPotionTests(PlayerTestCase):
    def test_witch_can_hold_both_potions(self):
        witch = self.make_player(
            role=Role.WITCH, has_life_potion=True, has_death_potion=True
        )
        self.assertTrue(witch.has_life_potion and witch.has_death_potion)

    def test_non_witch_with_life_potion_is_rejected(self):
        self.assertRejected(role=Role.SEER, has_life_potion=True)

    def test_non_witch_with_death_potion_is_rejected(self):
        self.assertRejected(role=Role.WEREWOLF, has_death_potion=True)


class PlayerDeathTests(PlayerTestCase):
    def test_dead_player_with_day_and_cause_is_valid(self):
        player = self.make_player(
            is_alive=False, died_on_day=1, death_cause=DeathCause.WOLVES
        )
        self.assertFalse(player.is_alive)

    def test_dead_player_without_cause_is_rejected(self):
        self.assertRejected(is_alive=False, died_on_day=1)

    def test_dead_player_without_day_is_rejected(self):
        self.assertRejected(is_alive=False, death_cause=DeathCause.VOTE)

    def test_alive_player_with_death_info_is_rejected(self):
        self.assertRejected(died_on_day=2, death_cause=DeathCause.WITCH)
