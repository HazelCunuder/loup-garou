import random
from unittest import mock

import httpx

from AI_log.models import AICallLog, CallStatus, CallType
from game.ai.decisions import InvalidDecision, decide, fallback_decision, validate
from game.ai.personas import PERSONAS, get_persona
from game.ai.prompts import DecisionType, legal_targets
from game.engine import player_view
from game.models import Personality, Phase, Player, Role
from night_time.models import NightAction, NightActionType as T

from ..helpers import GameTestCase
from .fakes import answer, fake_client


class ValidateTests(GameTestCase):
    def check(self, player, decision_type, raw):
        player.refresh_from_db()
        return validate(raw, player_view(self.game, player), decision_type, get_persona(player.personality))

    def assertInvalid(self, player, decision_type, raw):
        with self.assertRaises(InvalidDecision):
            self.check(player, decision_type, raw)

    def ai(self, *players):
        return next(p for p in players if not p.is_human)

    def test_chat_with_accusation(self):
        speaker = self.ai(*self.villagers)
        target = self.wolves[0]
        decision = self.check(speaker, DecisionType.DAY_CHAT, answer("parler", target.name.upper(), "Toi, là !"))
        self.assertEqual((decision.target_id, decision.message), (target.pk, "Toi, là !"))

    def test_chat_must_say_something(self):
        self.assertInvalid(self.ai(*self.villagers), DecisionType.DAY_CHAT, answer("parler", "", "   "))

    def test_markdown_emphasis_is_removed(self):
        decision = self.check(self.ai(*self.villagers), DecisionType.DAY_CHAT,
                              answer("parler", "", "Ton calme est *trop* parfait… **vraiment**."))
        self.assertEqual(decision.message, "Ton calme est trop parfait… vraiment.")

    def test_long_message_is_truncated(self):
        decision = self.check(self.ai(*self.villagers), DecisionType.DAY_CHAT, answer("parler", "", "a " * 400))
        self.assertLessEqual(len(decision.message), 250)

    def test_revealing_the_personality_is_rejected(self):
        speaker = self.ai(*self.villagers)
        label = get_persona(speaker.personality).label
        self.assertInvalid(speaker, DecisionType.DAY_CHAT, answer("parler", "", f"Bonjour, je suis {label.lower()}."))

    def test_message_naming_an_absent_player_is_rejected(self):
        speaker = self.ai(*self.villagers)
        in_game = {p.name for p in self.players}
        absent = next(n for n in ("Victor", "Margaux", "Inès", "Hugo") if n not in in_game)
        for name in (absent, "Nina", "Paul", "Basile"):
            with self.subTest(name=name):
                self.assertInvalid(speaker, DecisionType.DAY_CHAT, answer("parler", "", f"{name} ment, c'est sûr."))

    def test_message_naming_players_of_the_game_is_accepted(self):
        speaker = self.ai(*self.villagers)
        other = next(p for p in self.players if p != speaker)
        decision = self.check(speaker, DecisionType.DAY_CHAT, answer("parler", "", f"{other.name}, tu caches quoi ?"))
        self.assertIn(other.name, decision.message)

    def test_name_inside_a_longer_word_is_not_a_mention(self):
        speaker = self.ai(*self.villagers)
        decision = self.check(speaker, DecisionType.DAY_CHAT, answer("parler", "", "Paulette et Léandre dorment."))
        self.assertTrue(decision.message)

    def test_unknown_action_is_rejected(self):
        self.assertInvalid(self.ai(*self.villagers), DecisionType.DAY_VOTE, answer("tuer", self.seer.name))

    def test_blank_vote(self):
        decision = self.check(self.ai(*self.villagers), DecisionType.DAY_VOTE, answer("voter", ""))
        self.assertIsNone(decision.target_id)

    def test_vote_against_self_dead_or_unknown_is_rejected(self):
        voter = self.ai(*self.villagers)
        self.kill(self.villagers[2] if self.villagers[2] != voter else self.villagers[1])
        dead = next(p for p in self.players if not p.is_alive)
        for name in (voter.name, dead.name, "Personne"):
            with self.subTest(name=name):
                self.assertInvalid(voter, DecisionType.DAY_VOTE, answer("voter", name))

    def test_wolf_cannot_target_a_wolf(self):
        wolf = self.ai(*self.wolves)
        partner = next(w for w in self.wolves if w != wolf)
        self.assertInvalid(wolf, DecisionType.WOLF_TARGET, answer("devorer", partner.name))
        self.assertInvalid(wolf, DecisionType.WOLF_TARGET, answer("devorer", ""))

    def test_seer_needs_a_target(self):
        decision = self.check(self.seer, DecisionType.SEER_INSPECT, answer("sonder", self.wolves[0].name))
        self.assertEqual(decision.target_id, self.wolves[0].pk)
        self.assertEqual(decision.message, "")


class WitchValidateTests(ValidateTests):
    def setUp(self):
        super().setUp()
        self.victim = self.villagers[0]
        for wolf in self.wolves:
            NightAction.objects.create(game=self.game, night_number=1, actor=wolf,
                                       action_type=T.WOLF_TARGET, target=self.victim)
        self.set_phase(Phase.NIGHT_WITCH)

    def test_heal_and_poison(self):
        decision = self.check(self.witch, DecisionType.WITCH_DECISION,
                              answer("soigner_et_empoisonner", self.wolves[0].name))
        self.assertTrue(decision.heal)
        self.assertEqual(decision.kill_target_id, self.wolves[0].pk)

    def test_heal_ignores_any_target(self):
        decision = self.check(self.witch, DecisionType.WITCH_DECISION, answer("soigner", self.wolves[0].name))
        self.assertTrue(decision.heal)
        self.assertIsNone(decision.kill_target_id)

    def test_cannot_heal_and_poison_the_same_person(self):
        self.assertInvalid(self.witch, DecisionType.WITCH_DECISION,
                           answer("soigner_et_empoisonner", self.victim.name))

    def test_used_potions_are_rejected(self):
        Player.objects.filter(pk=self.witch.pk).update(has_life_potion=False, has_death_potion=False)
        self.assertInvalid(self.witch, DecisionType.WITCH_DECISION, answer("soigner"))
        self.assertInvalid(self.witch, DecisionType.WITCH_DECISION, answer("empoisonner", self.wolves[0].name))

    def test_poison_needs_a_target(self):
        self.assertInvalid(self.witch, DecisionType.WITCH_DECISION, answer("empoisonner", ""))


class FallbackTests(GameTestCase):
    def test_fallback_is_always_legal(self):
        rng = random.Random(0)
        for player in self.players:
            if player.is_human:
                continue
            view = player_view(self.game, player)
            persona = get_persona(player.personality)
            for decision_type in (DecisionType.DAY_CHAT, DecisionType.DAY_VOTE, DecisionType.SEER_INSPECT):
                legal = {p["id"] for p in legal_targets(view, decision_type)}
                for _ in range(50):
                    decision = fallback_decision(view, decision_type, persona, rng)
                    self.assertTrue(decision.used_fallback)
                    self.assertTrue(decision.target_id is None or decision.target_id in legal)

    def test_wolf_fallback_never_targets_a_wolf(self):
        view = player_view(self.game, self.wolves[0])
        persona = PERSONAS[Personality.IMPULSIF]
        wolves = {w.pk for w in self.wolves}
        for seed in range(50):
            decision = fallback_decision(view, DecisionType.WOLF_TARGET, persona, random.Random(seed))
            self.assertNotIn(decision.target_id, wolves)
            self.assertIn(decision.message, persona.fallback_lines["night"])

    def test_diplomat_abstains(self):
        view = player_view(self.game, self.villagers[0])
        decision = fallback_decision(view, DecisionType.DAY_VOTE, PERSONAS[Personality.DIPLOMATE])
        self.assertIsNone(decision.target_id)

    def test_chat_fallback_speaks_in_character(self):
        persona = PERSONAS[Personality.CYNIQUE]
        decision = fallback_decision(player_view(self.game, self.seer), DecisionType.DAY_CHAT, persona)
        self.assertIn(decision.message, persona.fallback_lines["chat"])

    def test_targeted_witch_saves_herself(self):
        for wolf in self.wolves:
            NightAction.objects.create(game=self.game, night_number=1, actor=wolf,
                                       action_type=T.WOLF_TARGET, target=self.witch)
        self.set_phase(Phase.NIGHT_WITCH)
        view = player_view(self.game, self.witch)
        decision = fallback_decision(view, DecisionType.WITCH_DECISION, PERSONAS[Personality.CYNIQUE])
        self.assertTrue(decision.heal)


class DecideTests(GameTestCase):
    human_role = Role.VILLAGER

    def setUp(self):
        super().setUp()
        self.set_phase(Phase.DAY_DEBATE)
        self.speaker = next(p for p in self.villagers if not p.is_human)

    def test_valid_answer_is_used_and_logged(self):
        client, sdk = fake_client(answer("parler", self.wolves[0].name, "Ce loup-là me regarde de travers.", "Il ment."))
        decision = decide(self.game, self.speaker, DecisionType.DAY_CHAT, client=client)
        self.assertFalse(decision.used_fallback)
        self.assertEqual(decision.message, "Ce loup-là me regarde de travers.")
        log = AICallLog.objects.get()
        self.assertEqual((log.status, log.call_type, log.used_fallback), (CallStatus.OK, CallType.CHAT, False))
        self.assertEqual((log.prompt_tokens, log.completion_tokens), (900, 60))
        self.speaker.refresh_from_db()
        self.assertEqual(self.speaker.last_thought, "Il ment.")

    def test_context_is_sent_without_double_escaping(self):
        client, sdk = fake_client(answer("parler", "", "Bonjour."))
        decide(self.game, self.speaker, DecisionType.DAY_CHAT, client=client)
        messages = sdk.calls[0]["messages"]
        self.assertIn("<memoire_privee>", messages[1]["content"])
        self.assertIn("Ta tâche", messages[0]["content"])
        self.assertIn(get_persona(self.speaker.personality).prompt_block(), messages[0]["content"])

    def test_temperature_follows_the_persona(self):
        client, sdk = fake_client(answer("parler", "", "Bonjour."))
        decide(self.game, self.speaker, DecisionType.DAY_CHAT, client=client)
        self.assertEqual(sdk.calls[0]["temperature"], get_persona(self.speaker.personality).temperature)

    def test_invalid_json_falls_back(self):
        client, _ = fake_client("pas du json")
        decision = decide(self.game, self.speaker, DecisionType.DAY_CHAT, client=client)
        self.assertTrue(decision.used_fallback)
        self.assertEqual(AICallLog.objects.get().status, CallStatus.INVALID_OUTPUT)

    def test_illegal_decision_falls_back_and_is_logged(self):
        self.set_phase(Phase.DAY_VOTE)
        client, _ = fake_client(answer("voter", self.speaker.name))
        decision = decide(self.game, self.speaker, DecisionType.DAY_VOTE, client=client)
        self.assertTrue(decision.used_fallback)
        self.assertNotEqual(decision.target_id, self.speaker.pk)
        log = AICallLog.objects.get()
        self.assertEqual((log.status, log.used_fallback), (CallStatus.INVALID_OUTPUT, True))

    def test_api_errors_and_timeouts_fall_back(self):
        for error, status in ((RuntimeError("429 Rate limit"), CallStatus.ERROR),
                              (httpx.ReadTimeout("lent"), CallStatus.TIMEOUT)):
            with self.subTest(status=status):
                AICallLog.objects.all().delete()
                client, _ = fake_client(error=error)
                decision = decide(self.game, self.speaker, DecisionType.DAY_CHAT, client=client)
                self.assertTrue(decision.used_fallback)
                self.assertTrue(decision.message)
                self.assertEqual(AICallLog.objects.get().status, status)

    def test_missing_api_key_falls_back(self):
        from game.services.mistral_client import MistralGameClient
        with mock.patch.dict("os.environ", {"MISTRAL_API_KEY": ""}):
            client = MistralGameClient(model="m", api_key=None, client=None)
            client._api_key = None
            decision = decide(self.game, self.speaker, DecisionType.DAY_CHAT, client=client)
        self.assertTrue(decision.used_fallback)

    def test_fake_backend_needs_no_network(self):
        with mock.patch.dict("os.environ", {"AI_BACKEND": "fake"}):
            decision = decide(self.game, self.speaker, DecisionType.DAY_CHAT)
        self.assertTrue(decision.used_fallback)
        self.assertFalse(AICallLog.objects.exists())

    def test_human_players_are_refused(self):
        with self.assertRaises(ValueError):
            decide(self.game, self.human, DecisionType.DAY_CHAT)
