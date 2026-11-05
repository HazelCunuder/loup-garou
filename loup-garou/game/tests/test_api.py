import json
from datetime import timedelta
from unittest import mock

from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from game.engine import create_game
from game.models import Channel, Game, Message, Phase, Role
from night_time.models import NightAction, NightActionType as T
from voting.models import Vote


class ApiTestCase(TestCase):
    def start(self, name="Alexandre", role=None, client=None):
        client = client or self.client
        data = {"name": name}
        if role:
            data["role"] = role
        response = client.post(reverse("game:new_game"), data)
        self.assertEqual(response.status_code, 302)
        game = Game.objects.get(pk=client.session["game_id"])
        return game, game.players.get(is_human=True)

    def set_phase(self, game, phase, **fields):
        Game.objects.filter(pk=game.pk).update(phase=phase, **fields)

    def post_json(self, name, data, client=None):
        return (client or self.client).post(
            reverse(name), json.dumps(data), content_type="application/json"
        )

    def state(self, **params):
        response = self.client.get(reverse("game:api_state"), params)
        self.assertEqual(response.status_code, 200)
        return response.json()


class StartPageTests(ApiTestCase):
    def test_start_page_without_game(self):
        response = self.client.get(reverse("game:village"))
        self.assertTemplateUsed(response, "game/start.html")
        self.assertContains(response, 'name="name"')

    def test_new_game_is_bound_to_the_session(self):
        game, human = self.start()
        self.assertEqual(human.name, "Alexandre")
        self.assertEqual(game.session_key, self.client.session.session_key)
        self.assertEqual(game.players.count(), 7)

    def test_empty_name_shows_an_error(self):
        response = self.client.post(reverse("game:new_game"), {"name": "  "})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "obligatoire", status_code=400)
        self.assertNotIn("game_id", self.client.session)

    @override_settings(DEBUG=True)
    def test_role_can_be_forced_in_debug(self):
        for key, role in (("loup", Role.WEREWOLF), ("voyante", Role.SEER),
                          ("sorciere", Role.WITCH), ("villageois", Role.VILLAGER)):
            with self.subTest(key=key):
                _, human = self.start(role=key, client=Client())
                self.assertEqual(human.role, role)

    @override_settings(DEBUG=False)
    def test_role_is_ignored_outside_debug(self):
        with mock.patch("game.views.create_game", wraps=create_game) as create:
            self.start(role="loup")
        self.assertIsNone(create.call_args.kwargs["human_role"])

    def test_leaving_returns_to_the_start_page(self):
        self.start()
        self.client.post(reverse("game:leave_game"))
        self.assertTemplateUsed(self.client.get(reverse("game:village")), "game/start.html")


class BoardPageTests(ApiTestCase):
    @override_settings(DEBUG=True)
    def test_board_shows_the_real_game(self):
        game, human = self.start(role="villageois")
        response = self.client.get(reverse("game:village"))
        self.assertTemplateUsed(response, "game/village.html")
        names = [p["name"] for p in response.context["players"]]
        self.assertEqual(names, [p.name for p in game.players.order_by("seat")])
        self.assertEqual(response.context["human"]["role"], "Villageois")

    @override_settings(DEBUG=True)
    def test_board_never_ships_secret_roles(self):
        self.start(role="villageois")
        response = self.client.get(reverse("game:village"))
        self.assertEqual(response.context["night"]["ai_roles"], {})
        self.assertIsNone(response.context["night"]["wolf_ally"])

    @override_settings(DEBUG=True)
    def test_wolf_board_knows_its_ally(self):
        game, human = self.start(role="loup")
        partner = game.players.get(role=Role.WEREWOLF, is_human=False)
        night = self.client.get(reverse("game:village")).context["night"]
        self.assertEqual(night["wolf_ally"]["name"], partner.name)
        self.assertEqual(night["ai_roles"], {partner.name: "Loup-Garou"})

    def test_refresh_keeps_the_same_game(self):
        game, _ = self.start()
        self.client.get(reverse("game:village"))
        self.client.get(reverse("game:village"))
        self.assertEqual(self.client.session["game_id"], str(game.pk))
        self.assertEqual(Game.objects.count(), 1)

    def test_human_name_is_escaped_in_scripts(self):
        self.start(name="O'Brien</script>")
        html = self.client.get(reverse("game:village")).content.decode()
        self.assertNotIn("O'Brien</script>", html)

    def test_page_loads_the_live_script_and_its_config(self):
        _, human = self.start()
        response = self.client.get(reverse("game:village"))
        html = response.content.decode()
        self.assertIn("game/live.js", html)
        self.assertIn('id="live-config"', html)
        config = response.context["live_config"]
        self.assertEqual(config["me_id"], human.pk)
        self.assertEqual(config["urls"]["state"], reverse("game:api_state"))
        self.assertTrue(config["csrf_token"])

    def test_demo_simulation_is_gone(self):
        self.start()
        html = self.client.get(reverse("game:village")).content.decode()
        for leftover in ("night-config", "mj-announcements", "lg:phase-active", "ai_roles"):
            self.assertNotIn(leftover, html)

    def test_seats_carry_player_ids(self):
        game, _ = self.start()
        html = self.client.get(reverse("game:village")).content.decode()
        for player in game.players.all():
            self.assertIn(f'data-player-id="{player.pk}"', html)

    @override_settings(DEBUG=True)
    def test_potions_are_only_shown_to_the_witch(self):
        for role, shown in (("villageois", False), ("loup", False), ("voyante", False), ("sorciere", True)):
            with self.subTest(role=role):
                client = Client()
                self.start(role=role, client=client)
                html = client.get(reverse("game:village")).content.decode()
                self.assertEqual('id="fiole-life"' in html, shown)
                self.assertEqual('id="fiole-death"' in html, shown)

    def test_new_game_button_and_warning_are_on_the_board(self):
        self.start()
        html = self.client.get(reverse("game:village")).content.decode()
        self.assertIn('id="new-game-form"', html)
        self.assertIn(f'action="{reverse("game:leave_game")}"', html)
        self.assertIn('id="new-game-modal"', html)
        self.assertIn("Abandonner et recommencer", html)

    def test_new_game_button_leads_to_the_start_page(self):
        old_game, _ = self.start()
        response = self.client.post(reverse("game:leave_game"), follow=True)
        self.assertTemplateUsed(response, "game/start.html")
        new_game, _ = self.start(name="Alexandre")
        self.assertNotEqual(old_game.pk, new_game.pk)

    def test_avatars_do_not_depend_on_personality(self):
        self.start()
        players = self.client.get(reverse("game:village")).context["players"]
        self.assertNotIn("🧠", {p["avatar"] for p in players})


class StateApiTests(ApiTestCase):
    def test_no_game_gives_404(self):
        response = self.client.get(reverse("game:api_state"))
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())

    def test_state_is_the_authorized_view(self):
        game, human = self.start()
        state = self.state()
        self.assertEqual(state["game"]["id"], str(game.pk))
        self.assertEqual(state["me"]["role"], human.role)
        others = [p for p in state["players"] if not p["is_me"]]
        if human.role != Role.WEREWOLF:
            self.assertTrue(all(p["role"] is None for p in others))

    def test_state_includes_banner_display(self):
        self.start()
        display = self.state()["display"]
        self.assertEqual(display["key"], "nuit")
        self.assertTrue(display["label"].startswith("Nuit 1"))

    def test_since_returns_only_new_messages(self):
        self.start()
        last = self.state()["messages"][-1]["id"]
        self.assertEqual(self.state(since=last)["messages"], [])
        self.assertEqual(len(self.state(since="abc")["messages"]), 1)

    def test_polling_advances_an_expired_phase(self):
        game, _ = self.start()
        self.set_phase(game, Phase.NIGHT_SEER, phase_deadline=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.state()["game"]["phase"], Phase.NIGHT_WOLVES)

    def test_each_session_only_sees_its_own_game(self):
        self.start()
        other = Client()
        self.assertEqual(other.get(reverse("game:api_state")).status_code, 404)

    def test_post_is_not_allowed_on_state(self):
        self.start()
        self.assertEqual(self.client.post(reverse("game:api_state")).status_code, 405)


class MessageApiTests(ApiTestCase):
    def test_public_message_during_debate(self):
        game, human = self.start()
        self.set_phase(game, Phase.DAY_DEBATE)
        response = self.post_json("game:api_message", {"text": "Je soupçonne quelqu'un."})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Message.objects.get(pk=response.json()["message_id"]).author, human)

    def test_refusals_return_400_with_a_reason(self):
        game, _ = self.start()
        cases = [
            ({"text": "La nuit…"}, "fermée la nuit"),
            ({"text": 42}, "doit être un texte"),
            ({"text": "x", "channel": "SECRET"}, "Canal inconnu"),
        ]
        for data, reason in cases:
            with self.subTest(data=data):
                response = self.post_json("game:api_message", data)
                self.assertEqual(response.status_code, 400)
                self.assertIn(reason, response.json()["error"])

    def test_invalid_json_returns_400(self):
        self.start()
        response = self.client.post(
            reverse("game:api_message"), "pas du json", content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)

    @override_settings(DEBUG=True)
    def test_human_wolf_can_use_the_wolves_channel(self):
        game, _ = self.start(role="loup")
        self.set_phase(game, Phase.NIGHT_WOLVES)
        response = self.post_json("game:api_message", {"text": "La voyante ?", "channel": Channel.WOLVES})
        self.assertEqual(response.status_code, 200)

    def test_csrf_is_enforced(self):
        client = Client(enforce_csrf_checks=True)
        self.start(client=Client())  # session différente, sans importance ici
        response = client.post(reverse("game:api_message"), "{}", content_type="application/json")
        self.assertEqual(response.status_code, 403)


class VoteApiTests(ApiTestCase):
    def setUp(self):
        self.game, self.human = self.start()
        self.set_phase(self.game, Phase.DAY_VOTE)
        self.other = self.game.players.exclude(pk=self.human.pk).first()

    def test_vote_and_abstention(self):
        response = self.post_json("game:api_vote", {"target_id": self.other.pk})
        self.assertEqual(response.json(), {"ok": True, "target_id": self.other.pk})
        self.assertEqual(Vote.objects.get(voter=self.human).target, self.other)

    def test_blank_vote(self):
        self.post_json("game:api_vote", {})
        self.assertIsNone(Vote.objects.get(voter=self.human).target)

    def test_vote_against_self_is_rejected_with_400(self):
        response = self.post_json("game:api_vote", {"target_id": self.human.pk})
        self.assertEqual(response.status_code, 400)

    def test_unknown_target_is_rejected(self):
        for target in (999999, "abc"):
            with self.subTest(target=target):
                self.assertEqual(self.post_json("game:api_vote", {"target_id": target}).status_code, 400)


@override_settings(DEBUG=True)
class NightApiTests(ApiTestCase):
    def test_seer_gets_the_revealed_role(self):
        game, human = self.start(role="voyante")
        wolf = game.players.filter(role=Role.WEREWOLF).first()
        response = self.post_json("game:api_night", {"action": "seer", "target_id": wolf.pk})
        self.assertEqual(response.json()["role"], Role.WEREWOLF)
        self.assertEqual(response.json()["role_label"], "Loup-Garou")
        self.assertEqual(self.state()["game"]["phase"], Phase.NIGHT_WOLVES)

    def test_wolf_chooses_a_victim(self):
        game, human = self.start(role="loup")
        self.set_phase(game, Phase.NIGHT_WOLVES)
        prey = game.players.exclude(role=Role.WEREWOLF).first()
        response = self.post_json("game:api_night", {"action": "wolf", "target_id": prey.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.state()["game"]["phase"], Phase.NIGHT_WITCH)

    def test_witch_decision(self):
        game, human = self.start(role="sorciere")
        victim = game.players.filter(role=Role.VILLAGER).first()
        for wolf in game.players.filter(role=Role.WEREWOLF):
            NightAction.objects.create(game=game, night_number=1, actor=wolf,
                                       action_type=T.WOLF_TARGET, target=victim)
        self.set_phase(game, Phase.NIGHT_WITCH)
        self.assertEqual(self.state()["private"]["wolf_victim"]["id"], victim.pk)
        response = self.post_json("game:api_night", {"action": "witch", "heal": True})
        self.assertEqual(response.json(), {"ok": True, "actions": [T.WITCH_HEAL]})

    def test_witch_heal_must_be_a_boolean(self):
        game, _ = self.start(role="sorciere")
        self.set_phase(game, Phase.NIGHT_WITCH)
        response = self.post_json("game:api_night", {"action": "witch", "heal": "oui"})
        self.assertEqual(response.status_code, 400)

    def test_unknown_or_unauthorized_action_is_rejected(self):
        game, _ = self.start(role="villageois")
        for data in ({"action": "fly"}, {"action": "seer", "target_id": 1}):
            with self.subTest(data=data):
                self.assertEqual(self.post_json("game:api_night", data).status_code, 400)
