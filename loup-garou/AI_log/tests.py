from django.db import IntegrityError, transaction
from django.test import TestCase

from AI_log.models import AICallLog, CallStatus, CallType
from game.models import Game, Personality, Phase, Player, Role


class AICallLogModelTests(TestCase):
    def setUp(self):
        self.game = Game.objects.create(session_key="s1")
        self.player = Player.objects.create(
            game=self.game, seat=0, name="Victor", role=Role.VILLAGER,
            personality=Personality.STRATEGE,
        )

    def log(self, game=None, **fields):
        fields.setdefault("status", CallStatus.OK)
        return AICallLog.objects.create(
            game=game or self.game, player=self.player, day_number=1,
            phase=Phase.DAY_DEBATE, call_type=CallType.CHAT,
            model_name="mistral-small-latest", **fields,
        )

    def test_successful_call(self):
        call = self.log(prompt_tokens=1100, completion_tokens=90, latency_ms=1800)
        self.assertEqual(call.total_tokens, 1190)
        self.assertFalse(call.used_fallback)

    def test_failed_call_with_fallback(self):
        call = self.log(status=CallStatus.TIMEOUT, used_fallback=True, error_message="> 3,5 s")
        self.assertTrue(call.used_fallback)

    def test_failed_call_without_fallback_is_rejected(self):
        for status in (CallStatus.TIMEOUT, CallStatus.ERROR, CallStatus.INVALID_OUTPUT):
            with self.subTest(status=status), transaction.atomic(), self.assertRaises(IntegrityError):
                self.log(status=status)

    def test_total_tokens_per_game(self):
        other = Game.objects.create(session_key="s2")
        self.log(prompt_tokens=1000, completion_tokens=100)
        self.log(prompt_tokens=1200, completion_tokens=80)
        AICallLog.objects.create(
            game=other, day_number=1, phase=Phase.DAY_VOTE, call_type=CallType.VOTE,
            model_name="m", status=CallStatus.OK, prompt_tokens=999,
        )
        self.assertEqual(self.game.ai_calls.total_tokens(), 2380)

    def test_total_tokens_without_calls_is_zero(self):
        self.assertEqual(self.game.ai_calls.total_tokens(), 0)
