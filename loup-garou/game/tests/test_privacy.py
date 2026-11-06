"""Conformité RGPD et AI Act : transparence IA, pas de tiers, information,
effacement et durée de conservation."""

import re
from datetime import timedelta
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from AI_log.models import AICallLog, CallStatus, CallType
from game.ai.orchestrator import _still
from game.models import Channel, Game, Message, MessageKind, Phase
from game.services.retention import expired_games, purge_expired_games

from .test_api import ApiTestCase

EXTERNAL = re.compile(r"""(?:src|href)\s*=\s*["'](?:https?:)?//|url\(\s*["']?(?:https?:)?//|@import""")


def chat(game, author, text="Bonjour"):
    return Message.objects.create(
        game=game,
        author=author,
        kind=MessageKind.CHAT,
        channel=Channel.PUBLIC,
        content=text,
        phase=Phase.DAY_DEBATE,
        day_number=1,
    )


def age(game, days):
    """Vieillit la partie de ``days`` jours (dernière activité comprise)."""
    past = timezone.now() - timedelta(days=days)
    Game.objects.filter(pk=game.pk).update(updated_at=past, phase_started_at=past)


# --------------------------------------------------------------------------- #
#  AI Act, art. 50 : l'utilisateur sait qu'il joue contre des IA              #
# --------------------------------------------------------------------------- #

class AIDisclosureTests(ApiTestCase):
    def test_start_page_says_the_other_players_are_ai(self):
        response = self.client.get(reverse("game:village"))
        self.assertContains(response, 'id="ai-disclosure"')
        self.assertContains(response, "Vous jouez contre des intelligences artificielles")

    def test_board_reminds_that_the_other_players_are_ai(self):
        self.start()
        response = self.client.get(reverse("game:village"))
        self.assertContains(response, 'id="ai-disclosure"')
        self.assertContains(response, "Les autres habitants sont des IA")

    def test_api_marks_ai_generated_messages(self):
        game, human = self.start()
        ai = game.players.filter(is_human=False).first()
        chat(game, ai, "Je suis innocent.")
        chat(game, human, "Moi aussi.")
        messages = {m["content"]: m for m in self.state()["messages"]}
        self.assertTrue(messages["Je suis innocent."]["author_is_ai"])
        self.assertFalse(messages["Moi aussi."]["author_is_ai"])
        announcement = next(m for m in messages.values() if m["kind"] == MessageKind.ANNOUNCEMENT)
        self.assertFalse(announcement["author_is_ai"])

    def test_live_script_labels_ai_authors(self):
        script = (Path(settings.BASE_DIR) / "static/game/live.js").read_text()
        self.assertIn("m.author_is_ai ? m.author_name + ' · IA'", script)


# --------------------------------------------------------------------------- #
#  RGPD : aucune adresse IP transmise à un tiers (polices, CDN)               #
# --------------------------------------------------------------------------- #

class NoThirdPartyTests(ApiTestCase):
    def assert_no_external_resource(self, response):
        html = response.content.decode()
        found = [html[m.start(): m.start() + 80] for m in EXTERNAL.finditer(html)]
        self.assertEqual(found, [])

    def test_start_page_loads_nothing_from_third_parties(self):
        self.assert_no_external_resource(self.client.get(reverse("game:village")))

    def test_board_loads_nothing_from_third_parties(self):
        self.start()
        self.assert_no_external_resource(self.client.get(reverse("game:village")))

    def test_self_hosted_fonts_are_all_present(self):
        fonts = Path(settings.BASE_DIR) / "static/vendor/fonts"
        css = (fonts / "fonts.css").read_text()
        self.assertNotIn("//", re.sub(r"/\*.*?\*/", "", css, flags=re.S))
        files = re.findall(r"url\(([^)]+)\)", css)
        self.assertTrue(files)
        for name in files:
            self.assertTrue((fonts / name).is_file(), name)

    def test_tailwind_is_served_locally(self):
        self.assertTrue((Path(settings.BASE_DIR) / "static/vendor/tailwind-play.js").is_file())


# --------------------------------------------------------------------------- #
#  RGPD, art. 13 : information des joueurs                                    #
# --------------------------------------------------------------------------- #

class PrivacyPageTests(ApiTestCase):
    def test_privacy_page_is_linked_from_start_page_and_board(self):
        url = reverse("game:privacy")
        self.assertContains(self.client.get(reverse("game:village")), f'href="{url}"')
        self.start()
        self.assertContains(self.client.get(reverse("game:village")), f'href="{url}"')

    @override_settings(
        PRIVACY_CONTROLLER="Équipe Loup-Garou",
        PRIVACY_CONTACT="rgpd@example.com",
        PRIVACY_HOSTING="Hébergeur Test (UE)",
        GAME_RETENTION_DAYS=30,
    )
    def test_privacy_page_gives_the_mandatory_information(self):
        response = self.client.get(reverse("game:privacy"))
        for text in (
            "Équipe Loup-Garou",
            "mailto:rgpd@example.com",
            "Hébergeur Test (UE)",
            "Mistral AI",
            "30 jours",
            "intelligences artificielles",
            "CNIL",
            "6.1.b",
        ):
            self.assertContains(response, text)

    def test_name_field_warns_that_it_goes_to_the_ai(self):
        self.assertContains(self.client.get(reverse("game:village")), "Un pseudonyme suffit")

    def test_privacy_page_counts_this_browser_games(self):
        self.start()
        self.assertContains(self.client.get(reverse("game:privacy")), "lié à 1 partie")


# --------------------------------------------------------------------------- #
#  RGPD, art. 17 : droit à l'effacement                                       #
# --------------------------------------------------------------------------- #

class DeleteDataTests(ApiTestCase):
    def delete(self, confirm=True, client=None):
        data = {"confirm": "1"} if confirm else {}
        return (client or self.client).post(reverse("game:delete_data"), data)

    def test_deletion_requires_confirmation(self):
        self.start()
        response = self.delete(confirm=False)
        self.assertRedirects(response, reverse("game:privacy"))
        self.assertEqual(Game.objects.count(), 1)

    def test_deletion_erases_every_game_of_the_browser_and_its_data(self):
        game, human = self.start()
        chat(game, human)
        AICallLog.objects.create(
            game=game, player=game.players.filter(is_human=False).first(), day_number=1,
            phase=Phase.DAY_DEBATE, call_type=CallType.CHAT, model_name="t", status=CallStatus.OK,
        )
        self.post_json("game:leave_game", {})
        self.start(name="Alexandre")  # deuxième partie, même navigateur
        old_session = self.client.session.session_key

        response = self.delete()

        self.assertRedirects(response, reverse("game:privacy") + "?supprime=1")
        self.assertEqual(Game.objects.count(), 0)
        self.assertEqual(Message.objects.count(), 0)
        self.assertEqual(AICallLog.objects.count(), 0)
        self.assertFalse(Session.objects.filter(session_key=old_session).exists())
        self.assertContains(self.client.get(response.url), "ont été supprimées")

    def test_deletion_never_touches_other_players_games(self):
        other = Client()
        self.start(client=other)
        self.start()
        self.delete()
        self.assertEqual(Game.objects.count(), 1)
        self.assertEqual(other.get(reverse("game:api_state")).status_code, 200)

    def test_game_in_progress_is_gone_after_deletion(self):
        self.start()
        self.delete()
        self.assertEqual(self.client.get(reverse("game:api_state")).status_code, 404)

    def test_deletion_without_any_game_is_harmless(self):
        response = self.delete()
        self.assertRedirects(response, reverse("game:privacy") + "?supprime=1")

    def test_deletion_is_post_only(self):
        self.assertEqual(self.client.get(reverse("game:delete_data")).status_code, 405)

    def test_background_ai_job_ignores_a_deleted_game(self):
        game, _ = self.start()
        version = game.version
        self.delete()
        self.assertIsNone(_still(game.pk, version))


# --------------------------------------------------------------------------- #
#  RGPD, art. 5.1.e : durée de conservation limitée                           #
# --------------------------------------------------------------------------- #

@override_settings(GAME_RETENTION_DAYS=30)
class RetentionTests(ApiTestCase):
    def test_only_inactive_games_expire(self):
        old, _ = self.start()
        recent, _ = self.start(client=Client())
        age(old, 31)
        age(recent, 29)
        self.assertEqual(list(expired_games()), [old])

    def test_recent_phase_change_keeps_the_game(self):
        game, _ = self.start()
        past = timezone.now() - timedelta(days=40)
        Game.objects.filter(pk=game.pk).update(updated_at=past)  # phase_started_at récent
        self.assertFalse(expired_games().exists())

    def test_purge_deletes_expired_games_with_their_data(self):
        game, human = self.start()
        chat(game, human)
        age(game, 31)
        self.assertEqual(purge_expired_games(), 1)
        self.assertFalse(Game.objects.exists())
        self.assertFalse(Message.objects.exists())

    def test_purge_deletes_expired_sessions(self):
        self.start()
        Session.objects.update(expire_date=timezone.now() - timedelta(seconds=1))
        purge_expired_games()
        self.assertFalse(Session.objects.exists())

    def test_new_game_purges_expired_games(self):
        old, _ = self.start(client=Client())
        age(old, 31)
        self.start()
        self.assertFalse(Game.objects.filter(pk=old.pk).exists())
        self.assertEqual(Game.objects.count(), 1)

    def test_command_dry_run_deletes_nothing(self):
        game, _ = self.start()
        age(game, 31)
        out = StringIO()
        call_command("purge_games", "--dry-run", stdout=out)
        self.assertIn("1 partie(s) de plus de 30 jours seraient effacées", out.getvalue())
        self.assertTrue(Game.objects.exists())

    def test_command_purges_with_custom_days(self):
        game, _ = self.start()
        age(game, 8)
        out = StringIO()
        call_command("purge_games", "--days", "7", stdout=out)
        self.assertIn("1 partie(s) de plus de 7 jours effacées", out.getvalue())
        self.assertFalse(Game.objects.exists())

    def test_session_cookie_does_not_outlive_the_games(self):
        self.assertLessEqual(settings.SESSION_COOKIE_AGE, settings.GAME_RETENTION_DAYS * 24 * 3600)
