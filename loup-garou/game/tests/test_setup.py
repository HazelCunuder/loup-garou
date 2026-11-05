from collections import Counter
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from game.engine import InvalidAction, create_game
from game.engine.rules import AI_NAMES
from game.models import Personality, Phase, Role


def signature(game):
    return [(p.seat, p.name, p.is_human, p.role, p.personality) for p in game.players.all()]


class CreateGameTests(TestCase):
    def setUp(self):
        self.game = create_game("session-1", "Alexandre", seed=1)
        self.players = list(self.game.players.all())

    def test_seven_players_with_mvp_composition(self):
        self.assertEqual(len(self.players), 7)
        self.assertEqual(
            Counter(p.role for p in self.players),
            {Role.WEREWOLF: 2, Role.VILLAGER: 3, Role.SEER: 1, Role.WITCH: 1},
        )
        self.assertEqual([p.seat for p in self.players], list(range(7)))

    def test_exactly_one_human_without_personality(self):
        humans = [p for p in self.players if p.is_human]
        self.assertEqual(len(humans), 1)
        self.assertEqual(humans[0].name, "Alexandre")
        self.assertIsNone(humans[0].personality)

    def test_six_ai_with_six_distinct_personalities(self):
        ais = [p for p in self.players if not p.is_human]
        self.assertEqual(len(ais), 6)
        self.assertEqual({p.personality for p in ais}, set(Personality.values))
        self.assertTrue(all(p.name in AI_NAMES for p in ais))

    def test_only_the_witch_holds_both_potions(self):
        for p in self.players:
            expected = p.role == Role.WITCH
            self.assertEqual((p.has_life_potion, p.has_death_potion), (expected, expected))

    def test_everyone_starts_alive(self):
        self.assertTrue(all(p.is_alive for p in self.players))

    def test_game_opens_on_seer_night_with_timer(self):
        self.assertEqual(self.game.phase, Phase.NIGHT_SEER)
        self.assertEqual(self.game.day_number, 1)
        self.assertEqual(self.game.session_key, "session-1")
        self.assertEqual(self.game.seed, 1)
        delta = self.game.phase_deadline - self.game.phase_started_at
        self.assertEqual(delta, timedelta(seconds=45))
        self.assertLessEqual(self.game.phase_started_at, timezone.now())


class DeterministicDrawTests(TestCase):
    def test_same_seed_gives_same_draw(self):
        a = create_game("s", "Alexandre", seed=1234)
        b = create_game("s", "Alexandre", seed=1234)
        self.assertEqual(signature(a), signature(b))

    def test_different_seeds_give_different_draws(self):
        self.assertNotEqual(
            signature(create_game("s", "Alexandre", seed=1)),
            signature(create_game("s", "Alexandre", seed=2)),
        )

    def test_random_seed_is_generated_and_stored(self):
        game = create_game("s", "Alexandre")
        replay = create_game("s", "Alexandre", seed=game.seed)
        self.assertEqual(signature(game), signature(replay))

    def test_human_can_receive_every_role(self):
        roles = {
            create_game("s", "Alexandre", seed=seed).players.get(is_human=True).role
            for seed in range(40)
        }
        self.assertEqual(roles, set(Role.values))


class HumanNameTests(TestCase):
    def test_name_is_stripped(self):
        game = create_game("s", "  Alexandre  ", seed=1)
        self.assertTrue(game.players.filter(is_human=True, name="Alexandre").exists())

    def test_empty_name_is_rejected(self):
        for name in ("", "   ", None):
            with self.subTest(name=name), self.assertRaises(InvalidAction):
                create_game("s", name)

    def test_too_long_name_is_rejected(self):
        with self.assertRaises(InvalidAction):
            create_game("s", "x" * 33)

    def test_human_name_is_never_given_to_an_ai(self):
        for seed in range(20):
            game = create_game("s", "victor", seed=seed)
            names = [p.name.casefold() for p in game.players.all()]
            self.assertEqual(names.count("victor"), 1)

    def test_unsupported_player_count_is_rejected(self):
        with self.assertRaises(InvalidAction):
            create_game("s", "Alexandre", player_count=8)


class ForcedHumanRoleTests(TestCase):
    def test_human_gets_the_forced_role_and_composition_is_kept(self):
        for role in Role.values:
            with self.subTest(role=role):
                game = create_game("s", "Alexandre", seed=3, human_role=role)
                self.assertEqual(game.players.get(is_human=True).role, role)
                self.assertEqual(
                    Counter(p.role for p in game.players.all()),
                    {Role.WEREWOLF: 2, Role.VILLAGER: 3, Role.SEER: 1, Role.WITCH: 1},
                )

    def test_unknown_role_is_rejected(self):
        with self.assertRaises(InvalidAction):
            create_game("s", "Alexandre", human_role="MAIRE")
