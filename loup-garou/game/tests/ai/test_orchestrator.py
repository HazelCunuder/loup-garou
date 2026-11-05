import json
import time
from datetime import timedelta
from unittest import mock

from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from game.ai import orchestrator
from game.ai.orchestrator import pick_speakers, schedule
from game.engine import advance, create_game, submit_message, submit_vote, submit_wolf_target
from game.models import Channel, Game, MessageKind, Phase, Role
from game.services.game_loop import tick
from night_time.models import NightAction, NightActionType as T
from voting.models import Vote

from ..helpers import GameTestCase

INLINE = dict(
    AI_ORCHESTRATOR=True,
    AI_RUN_INLINE=True,
    AI_DEBATE_GAP=0,
    AI_PACING=0,
    AI_DEBATE_MAX_MESSAGES=4,
)


@override_settings(**INLINE)
class OrchestratorTestCase(GameTestCase):
    """Orchestrateur synchrone, IA en repli procédural (aucun appel réseau)."""

    human_role = Role.VILLAGER

    def setUp(self):
        env = mock.patch.dict("os.environ", {"AI_BACKEND": "fake"})
        env.start()
        self.addCleanup(env.stop)
        orchestrator.reset()
        self.addCleanup(orchestrator.reset)
        super().setUp()

    def go_to(self, phase):
        """Avance réellement (annonces, version) jusqu'à ``phase``, sans orchestrateur."""
        with override_settings(AI_ORCHESTRATOR=False):
            while self.game.phase != phase:
                self.game = advance(self.game)
        self.refresh()

    def ai_messages(self, channel=Channel.PUBLIC):
        return self.game.messages.filter(
            kind=MessageKind.CHAT, channel=channel, author__is_human=False
        )


class NightOrchestrationTests(OrchestratorTestCase):
    def test_ai_night_runs_by_itself_until_dawn(self):
        schedule(self.game)
        self.game.refresh_from_db()
        self.assertEqual(self.game.phase, Phase.DAWN)
        self.assertTrue(NightAction.objects.filter(action_type=T.SEER_INSPECT).exists())
        targets = set(
            NightAction.objects.filter(action_type=T.WOLF_TARGET).values_list("target_id", flat=True)
        )
        self.assertEqual(len(targets), 1, "les deux loups IA visent la même cible")
        self.assertTrue(
            NightAction.objects.filter(actor__role=Role.WITCH).exists()
            or not self.witch.is_alive
        )

    def test_nothing_runs_when_disabled(self):
        with override_settings(AI_ORCHESTRATOR=False):
            schedule(self.game)
        self.assertFalse(NightAction.objects.exists())


class HumanSeerTests(OrchestratorTestCase):
    human_role = Role.SEER

    def test_ai_waits_for_the_human_seer(self):
        schedule(self.game)
        self.game.refresh_from_db()
        self.assertEqual(self.game.phase, Phase.NIGHT_SEER)
        self.assertFalse(NightAction.objects.exists())


class HumanWolfTests(OrchestratorTestCase):
    human_role = Role.WEREWOLF

    def setUp(self):
        super().setUp()
        self.go_to(Phase.NIGHT_WOLVES)
        self.partner = next(w for w in self.wolves if not w.is_human)

    def test_partner_proposes_then_answers_each_message(self):
        schedule(self.game)
        self.assertEqual(self.ai_messages(Channel.WOLVES).count(), 1)
        proposal = NightAction.objects.get(actor=self.partner, action_type=T.WOLF_TARGET)
        self.assertNotEqual(proposal.target.role, Role.WEREWOLF)
        self.game.refresh_from_db()
        self.assertEqual(self.game.phase, Phase.NIGHT_WOLVES, "on attend le choix humain")

        submit_message(self.game, self.human, "Et si on mangeait la voyante ?", Channel.WOLVES)
        schedule(self.game)
        self.assertEqual(self.ai_messages(Channel.WOLVES).count(), 2)
        schedule(self.game)  # pas de nouvelle réponse sans nouveau message
        self.assertEqual(self.ai_messages(Channel.WOLVES).count(), 2)

    def test_partner_follows_the_human_choice(self):
        schedule(self.game)
        prey = self.villagers[0]
        submit_wolf_target(self.game, self.human, prey)
        targets = set(
            NightAction.objects.filter(action_type=T.WOLF_TARGET).values_list("target_id", flat=True)
        )
        self.assertEqual(targets, {prey.pk})


class DebateTests(OrchestratorTestCase):
    def setUp(self):
        super().setUp()
        self.go_to(Phase.DAY_DEBATE)

    def test_debate_keeps_going_up_to_the_limit(self):
        schedule(self.game)
        count = self.ai_messages().count()
        self.assertGreaterEqual(count, 4)
        self.assertLessEqual(count, 5)  # une salve de 2 peut déborder d'un message
        self.assertGreater(len(set(self.ai_messages().values_list("author", flat=True))), 2)

    def test_human_message_always_gets_an_answer(self):
        schedule(self.game)
        before = self.ai_messages().count()
        named = next(p for p in self.players if not p.is_human)
        submit_message(self.game, self.human, f"{named.name}, tu étais où cette nuit ?")
        schedule(self.game)
        replies = self.ai_messages().order_by("id")[before:]
        self.assertTrue(replies)
        self.assertEqual(replies[0].author, named)

    def test_silent_gap_is_respected(self):
        with override_settings(AI_DEBATE_GAP=60):
            schedule(self.game)
        self.assertEqual(self.ai_messages().count(), 0)

    def test_pick_speakers_prefers_named_then_quiet_players(self):
        ais = [p for p in self.players if not p.is_human]
        for _ in range(2):
            submit_message(self.game, ais[0], "Je parle beaucoup.")
        speakers = pick_speakers(self.game, 2, f"Et toi {ais[3].name} ?")
        self.assertEqual(speakers[0], ais[3])
        self.assertNotEqual(speakers[1], ais[0])

    def test_dead_players_never_speak(self):
        ais = [p for p in self.players if not p.is_human]
        self.kill(ais[0])
        schedule(self.game)
        self.assertFalse(self.ai_messages().filter(author=ais[0]).exists())


class VoteOrchestrationTests(OrchestratorTestCase):
    def setUp(self):
        super().setUp()
        self.go_to(Phase.DAY_VOTE)

    def test_every_ai_votes_once_then_waits_for_the_human(self):
        schedule(self.game)
        schedule(self.game)
        self.assertEqual(Vote.objects.filter(voter__is_human=False).count(), 6)
        self.game.refresh_from_db()
        self.assertEqual(self.game.phase, Phase.DAY_VOTE)
        submit_vote(self.game, self.human, None)
        self.game.refresh_from_db()
        self.assertEqual(self.game.phase, Phase.VOTE_RESULT)


class StaleJobTests(OrchestratorTestCase):
    def test_refused_action_is_ignored(self):
        self.go_to(Phase.DAY_DEBATE)
        result = orchestrator._safely(submit_vote, self.game, self.seer, None)
        self.assertIsNone(result)


class FullGameTests(OrchestratorTestCase):
    def test_passive_human_game_reaches_the_end(self):
        for _ in range(150):
            self.game.refresh_from_db()
            if self.game.is_finished:
                break
            Game.objects.filter(pk=self.game.pk).update(
                phase_deadline=timezone.now() - timedelta(seconds=1)
            )
            self.game = tick(self.game)
        self.game.refresh_from_db()
        self.assertEqual(self.game.phase, Phase.GAME_OVER)
        self.assertIsNotNone(self.game.winner)


class ApiTriggersAgentsTests(OrchestratorTestCase):
    def test_human_message_through_the_api_gets_an_answer(self):
        self.client.post(reverse("game:new_game"), {"name": "Alexandre"})
        game = Game.objects.get(pk=self.client.session["game_id"])
        self.game = game
        self.go_to(Phase.DAY_DEBATE)
        with override_settings(AI_DEBATE_MAX_MESSAGES=0):
            self.client.post(
                reverse("game:api_message"),
                json.dumps({"text": "Bonjour à tous !"}),
                content_type="application/json",
            )
        self.assertTrue(self.ai_messages().exists())


@override_settings(AI_ORCHESTRATOR=True, AI_RUN_INLINE=False, AI_PACING=0)
class BackgroundThreadTests(TransactionTestCase):
    """Le vrai mode d'exécution : threads d'arrière-plan avec leur propre connexion."""

    def setUp(self):
        env = mock.patch.dict("os.environ", {"AI_BACKEND": "fake"})
        env.start()
        self.addCleanup(env.stop)
        orchestrator.reset()

    def test_votes_are_cast_in_the_background(self):
        game = create_game("s", "Alexandre", seed=7, human_role=Role.VILLAGER)
        with override_settings(AI_ORCHESTRATOR=False):
            while game.phase != Phase.DAY_VOTE:
                game = advance(game)
        schedule(game)
        # On attend la fin de la tâche dans le registre, sans lire la base :
        # la SQLite en mémoire des tests verrouille les tables au lieu
        # d'attendre (contrairement à la base fichier en mode WAL).
        key = f"{game.pk}:{game.version}:votes"
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and (key not in orchestrator._done or orchestrator._running):
            time.sleep(0.05)
        self.assertIn(key, orchestrator._done)
        self.assertEqual(Vote.objects.filter(voter__is_human=False).count(), 6)
