from django.test import SimpleTestCase

from game.models import Phase, Winner
from game.presenters import status_phase


def view(phase, winner=None):
    return {"game": {"phase": phase, "phase_label": Phase(phase).label, "day": 2, "winner": winner}}


class StatusPhaseTests(SimpleTestCase):
    def test_banner_key_follows_the_phase(self):
        expected = {
            Phase.NIGHT_SEER: "nuit", Phase.NIGHT_WOLVES: "nuit", Phase.NIGHT_WITCH: "nuit",
            Phase.DAWN: "jour", Phase.DAY_DEBATE: "jour", Phase.DAY_VOTE: "vote",
            Phase.VOTE_RESULT: "jour",
        }
        for phase, key in expected.items():
            with self.subTest(phase=phase):
                self.assertEqual(status_phase(view(phase))["key"], key)

    def test_labels_are_short_and_not_redundant(self):
        self.assertEqual(status_phase(view(Phase.DAY_DEBATE))["label"], "Jour 2 · Débat")
        self.assertEqual(status_phase(view(Phase.NIGHT_WOLVES))["label"], "Nuit 2 · Les loups")
        self.assertEqual(status_phase(view(Phase.DAY_VOTE))["label"], "Jour 2 · Le vote")

    def test_labels_show_the_day_number(self):
        self.assertTrue(status_phase(view(Phase.NIGHT_WOLVES))["label"].startswith("Nuit 2"))
        self.assertTrue(status_phase(view(Phase.DAY_VOTE))["label"].startswith("Jour 2"))

    def test_game_over_shows_the_winner(self):
        self.assertEqual(status_phase(view(Phase.GAME_OVER, Winner.WOLVES))["label"], "Victoire des loups-garous")
        self.assertEqual(status_phase(view(Phase.GAME_OVER, Winner.VILLAGE))["label"], "Victoire du village")
