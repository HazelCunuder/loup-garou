import json

from game.engine import player_view, submit_message
from game.models import Channel, Game, GameStatus, Phase, Player, Role, Winner
from night_time.models import NightAction, NightActionType as T
from voting.models import Vote

from .helpers import GameTestCase


def roles_seen(view):
    return {p["name"]: p["role"] for p in view["players"] if p["role"]}


class ViewTestCase(GameTestCase):
    def view(self, viewer, **kwargs):
        self.game.refresh_from_db()
        return player_view(self.game, viewer, **kwargs)


class VillagerViewTests(ViewTestCase):
    def test_villager_only_knows_own_role(self):
        villager = self.villagers[0]
        self.assertEqual(roles_seen(self.view(villager)), {villager.name: Role.VILLAGER})

    def test_dead_players_roles_are_public(self):
        self.kill(self.wolves[0])
        seen = roles_seen(self.view(self.villagers[0]))
        self.assertEqual(seen[self.wolves[0].name], Role.WEREWOLF)
        self.assertNotIn(self.wolves[1].name, seen)

    def test_villager_never_sees_the_wolves_channel(self):
        self.set_phase(Phase.NIGHT_WOLVES)
        submit_message(self.game, self.wolves[0], "Cette nuit : la voyante.", Channel.WOLVES)
        view = self.view(self.villagers[0])
        self.assertTrue(all(m["channel"] == Channel.PUBLIC for m in view["messages"]))
        self.assertNotIn("la voyante.", json.dumps(view, ensure_ascii=False))

    def test_private_data_of_others_never_leaks(self):
        Player.objects.filter(pk=self.wolves[0].pk).update(last_thought="SECRET-LOUP")
        dump = json.dumps(self.view(self.villagers[0]), ensure_ascii=False)
        self.assertNotIn("SECRET-LOUP", dump)
        self.assertNotIn("wolf_partners", dump)
        self.assertNotIn("inspections", dump)
        self.assertNotIn("potions", dump)


class WolfViewTests(ViewTestCase):
    def test_wolf_knows_its_partner_and_reads_the_channel(self):
        self.set_phase(Phase.NIGHT_WOLVES)
        submit_message(self.game, self.wolves[1], "La sorcière ?", Channel.WOLVES)
        view = self.view(self.wolves[0])
        self.assertEqual(roles_seen(view)[self.wolves[1].name], Role.WEREWOLF)
        self.assertEqual(view["private"]["wolf_partners"][0]["name"], self.wolves[1].name)
        self.assertIn(Channel.WOLVES, {m["channel"] for m in view["messages"]})


class SeerViewTests(ViewTestCase):
    def test_seer_remembers_her_inspections(self):
        NightAction.objects.create(
            game=self.game, night_number=1, actor=self.seer,
            action_type=T.SEER_INSPECT, target=self.wolves[0], revealed_role=Role.WEREWOLF,
        )
        view = self.view(self.seer)
        self.assertEqual(roles_seen(view)[self.wolves[0].name], Role.WEREWOLF)
        self.assertEqual(
            view["private"]["inspections"],
            [{
                "night": 1, "target_id": self.wolves[0].pk, "target_name": self.wolves[0].name,
                "role": Role.WEREWOLF, "role_label": "Loup-Garou",
            }],
        )


class WitchViewTests(ViewTestCase):
    def setUp(self):
        super().setUp()
        for wolf in self.wolves:
            NightAction.objects.create(
                game=self.game, night_number=1, actor=wolf,
                action_type=T.WOLF_TARGET, target=self.villagers[0],
            )

    def test_witch_sees_the_victim_only_during_her_turn(self):
        self.set_phase(Phase.NIGHT_WOLVES)
        self.assertIsNone(self.view(self.witch)["private"]["wolf_victim"])
        self.set_phase(Phase.NIGHT_WITCH)
        private = self.view(self.witch)["private"]
        self.assertEqual(private["wolf_victim"]["name"], self.villagers[0].name)
        self.assertEqual(private["potions"], {"life": True, "death": True})


class TurnAndVotesViewTests(ViewTestCase):
    def test_turn_tells_who_must_act(self):
        self.assertEqual(self.view(self.seer)["turn"], {"action": "seer", "expected": True, "done": False})
        self.assertEqual(self.view(self.villagers[0])["turn"]["action"], None)

    def test_turn_is_done_after_acting(self):
        self.set_phase(Phase.DAY_VOTE)
        Vote.objects.create(game=self.game, day_number=1, voter=self.seer, target=None)
        self.assertTrue(self.view(self.seer)["turn"]["done"])

    def test_votes_are_revealed_once_the_vote_is_closed(self):
        self.set_phase(Phase.DAY_VOTE)
        Vote.objects.create(game=self.game, day_number=1, voter=self.seer, target=self.wolves[0])
        self.assertEqual(self.view(self.villagers[0])["votes"], [])
        self.set_phase(Phase.VOTE_RESULT)
        votes = self.view(self.villagers[0])["votes"]
        self.assertEqual((votes[0]["voter_name"], votes[0]["target_name"]), (self.seer.name, self.wolves[0].name))


class GeneralViewTests(ViewTestCase):
    def test_since_id_returns_only_new_messages(self):
        first_id = self.view(self.human)["messages"][-1]["id"]
        self.set_phase(Phase.DAY_DEBATE)
        submit_message(self.game, self.human, "Nouveau")
        messages = self.view(self.human, since_id=first_id)["messages"]
        self.assertEqual([m["content"] for m in messages], ["Nouveau"])

    def test_game_over_reveals_every_role(self):
        Game.objects.filter(pk=self.game.pk).update(
            phase=Phase.GAME_OVER, status=GameStatus.FINISHED, winner=Winner.WOLVES
        )
        self.assertEqual(len(roles_seen(self.view(self.villagers[0]))), 7)

    def test_view_is_json_serializable_with_deadline(self):
        view = self.view(self.human)
        json.dumps(view)
        self.assertEqual(view["game"]["phase"], Phase.NIGHT_SEER)
        self.assertIsNotNone(view["game"]["phase_deadline"])
        self.assertEqual(view["me"]["name"], "Alexandre")
