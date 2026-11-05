from game.engine import advance
from game.models import Channel, MessageKind, Phase

from .helpers import GameTestCase


class AnnouncementTests(GameTestCase):
    def test_game_start_is_announced(self):
        first = self.game.messages.get()
        self.assertEqual(first.kind, MessageKind.ANNOUNCEMENT)
        self.assertIsNone(first.author)
        self.assertEqual(first.channel, Channel.PUBLIC)
        self.assertIn("Nuit 1", first.content)

    def test_each_day_phase_is_announced(self):
        self.set_phase(Phase.DAWN)
        advance(self.game)
        self.assertIn("débat est ouvert", self.last_announcement())
        advance(self.game)
        self.assertIn("Place au vote", self.last_announcement())

    def test_nightfall_is_announced_once_with_the_new_day(self):
        self.set_phase(Phase.VOTE_RESULT)
        game = advance(self.game)
        message = game.messages.last()
        self.assertEqual((message.content, message.day_number), ("Nuit 2. Le village s'endort…", 2))
        count = len(self.announcements())
        advance(game)  # voyante → loups : pas de nouvelle annonce
        self.assertEqual(len(self.announcements()), count)

    def test_game_over_names_the_winner(self):
        self.kill(*self.wolves)
        advance(self.game)
        self.assertIn("Victoire du village", self.last_announcement())

    def test_wolves_victory_is_announced(self):
        self.kill(*self.non_wolves[:3])
        advance(self.game)
        self.assertIn("Victoire des loups-garous", self.last_announcement())
