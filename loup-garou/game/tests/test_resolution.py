from game.engine import advance
from game.engine.resolution import resolve_night, resolve_vote, wolf_victim
from game.models import DeathCause, Phase, Player
from night_time.models import NightAction, NightActionType as T
from voting.models import Vote

from .helpers import GameTestCase


class NightTestCase(GameTestCase):
    def act(self, actor, action_type, target=None):
        NightAction.objects.create(
            game=self.game, night_number=self.game.day_number, actor=actor,
            action_type=action_type, target=target,
        )

    def wolves_target(self, *targets):
        for wolf, target in zip(self.wolves, targets):
            self.act(wolf, T.WOLF_TARGET, target)

    def alive(self, player):
        return Player.objects.get(pk=player.pk).is_alive


class WolfNightTests(NightTestCase):
    def test_agreeing_wolves_kill_their_target(self):
        victim = self.villagers[0]
        self.wolves_target(victim, victim)
        self.assertEqual(resolve_night(self.game), [victim])
        victim.refresh_from_db()
        self.assertFalse(victim.is_alive)
        self.assertEqual((victim.died_on_day, victim.death_cause), (1, DeathCause.WOLVES))

    def test_disagreeing_wolves_kill_nobody(self):
        # Cadrage : Loup 1 vise A, Loup 2 vise B → 0 victime au matin.
        self.wolves_target(self.villagers[0], self.villagers[1])
        self.assertIsNone(wolf_victim(self.game))
        self.assertEqual(resolve_night(self.game), [])
        self.assertIn("Personne n'est mort", self.last_announcement())

    def test_lone_wolf_decides_alone(self):
        self.kill(self.wolves[0])
        self.act(self.wolves[1], T.WOLF_TARGET, self.seer)
        self.assertEqual(resolve_night(self.game), [self.seer])

    def test_wolf_who_did_not_act_does_not_block_the_other(self):
        self.act(self.wolves[0], T.WOLF_TARGET, self.seer)
        self.assertEqual(resolve_night(self.game), [self.seer])

    def test_quiet_night(self):
        self.assertEqual(resolve_night(self.game), [])

    def test_only_this_night_counts(self):
        NightAction.objects.create(
            game=self.game, night_number=2, actor=self.wolves[0],
            action_type=T.WOLF_TARGET, target=self.seer,
        )
        self.assertEqual(resolve_night(self.game), [])

    def test_dawn_announcement_reveals_the_role(self):
        self.wolves_target(self.seer, self.seer)
        resolve_night(self.game)
        message = self.game.messages.last()
        self.assertEqual(message.phase, Phase.DAWN)
        self.assertIn(self.seer.name, message.content)
        self.assertIn("la Voyante", message.content)


class WitchNightTests(NightTestCase):
    def test_life_potion_saves_the_victim(self):
        victim = self.villagers[0]
        self.wolves_target(victim, victim)
        self.act(self.witch, T.WITCH_HEAL, victim)
        self.assertEqual(resolve_night(self.game), [])
        self.assertTrue(self.alive(victim))
        self.witch.refresh_from_db()
        self.assertFalse(self.witch.has_life_potion)
        self.assertTrue(self.witch.has_death_potion)

    def test_witch_can_save_herself(self):
        # Cadrage : sorcière ciblée utilise la potion de vie → elle survit.
        self.wolves_target(self.witch, self.witch)
        self.act(self.witch, T.WITCH_HEAL, self.witch)
        resolve_night(self.game)
        self.assertTrue(self.alive(self.witch))

    def test_death_potion_kills(self):
        self.act(self.witch, T.WITCH_KILL, self.wolves[0])
        self.assertEqual(resolve_night(self.game), [self.wolves[0]])
        wolf = Player.objects.get(pk=self.wolves[0].pk)
        self.assertEqual(wolf.death_cause, DeathCause.WITCH)
        self.witch.refresh_from_db()
        self.assertFalse(self.witch.has_death_potion)

    def test_heal_and_kill_in_the_same_night(self):
        victim = self.villagers[0]
        self.wolves_target(victim, victim)
        self.act(self.witch, T.WITCH_HEAL, victim)
        self.act(self.witch, T.WITCH_KILL, self.wolves[1])
        self.assertEqual(resolve_night(self.game), [self.wolves[1]])
        self.witch.refresh_from_db()
        self.assertFalse(self.witch.has_life_potion or self.witch.has_death_potion)

    def test_poisoning_the_wolves_victim_kills_once(self):
        victim = self.villagers[0]
        self.wolves_target(victim, victim)
        self.act(self.witch, T.WITCH_KILL, victim)
        self.assertEqual(resolve_night(self.game), [victim])
        self.assertEqual(Player.objects.get(pk=victim.pk).death_cause, DeathCause.WOLVES)

    def test_used_potion_has_no_effect(self):
        Player.objects.filter(pk=self.witch.pk).update(has_life_potion=False, has_death_potion=False)
        victim = self.villagers[0]
        self.wolves_target(victim, victim)
        self.act(self.witch, T.WITCH_HEAL, victim)
        self.act(self.witch, T.WITCH_KILL, self.wolves[0])
        self.assertEqual(resolve_night(self.game), [victim])

    def test_two_deaths_are_announced_together(self):
        self.wolves_target(self.seer, self.seer)
        self.act(self.witch, T.WITCH_KILL, self.villagers[0])
        resolve_night(self.game)
        text = self.last_announcement()
        self.assertIn("ont été retrouvés morts", text)
        self.assertIn(self.seer.name, text)
        self.assertIn(self.villagers[0].name, text)

    def test_night_is_resolved_when_advancing_to_dawn(self):
        victim = self.villagers[0]
        self.wolves_target(victim, victim)
        self.set_phase(Phase.NIGHT_WITCH)
        game = advance(self.game)
        self.assertEqual(game.phase, Phase.DAWN)
        self.assertFalse(self.alive(victim))


class VoteResolutionTests(GameTestCase):
    def setUp(self):
        super().setUp()
        self.set_phase(Phase.DAY_VOTE)

    def votes(self, *pairs):
        for voter, target in pairs:
            Vote.objects.create(game=self.game, day_number=1, voter=voter, target=target)

    def test_tie_eliminates_nobody(self):
        # Cadrage : vote 3-3-1 → 0 mort.
        a, b, c = self.villagers
        others = [p for p in self.players if p not in (a, b)]
        self.votes(
            (others[0], a), (others[1], a), (others[2], a),
            (others[3], b), (others[4], b), (a, b),
            (b, c),
        )
        self.assertIsNone(resolve_vote(self.game))
        self.assertTrue(all(p.is_alive for p in self.game.players.all()))
        self.assertIn("Égalité", self.last_announcement())

    def test_abstentions_do_not_count(self):
        # Cadrage : 2 votes A, 1 vote B, 4 abstentions → A éliminé.
        a, b = self.villagers[0], self.villagers[1]
        voters = [p for p in self.players if p not in (a, b)]
        self.votes((voters[0], a), (voters[1], a), (voters[2], b))
        self.votes((voters[3], None), (voters[4], None), (a, None), (b, None))
        self.assertEqual(resolve_vote(self.game), a)
        a.refresh_from_db()
        self.assertEqual((a.is_alive, a.death_cause), (False, DeathCause.VOTE))

    def test_everybody_abstains(self):
        self.votes(*[(p, None) for p in self.players])
        self.assertIsNone(resolve_vote(self.game))
        self.assertIn("Personne n'a été désigné", self.last_announcement())

    def test_no_vote_at_all_after_timer(self):
        # Cadrage : expiration du timer → abstention.
        self.assertIsNone(resolve_vote(self.game))

    def test_elimination_announcement_reveals_role(self):
        wolf = self.wolves[0]
        self.votes(*[(p, wolf) for p in self.players if p != wolf])
        resolve_vote(self.game)
        text = self.last_announcement()
        self.assertIn(wolf.name, text)
        self.assertIn("un Loup-Garou", text)
        self.assertIn("6 voix", text)

    def test_vote_is_resolved_when_advancing(self):
        target = self.villagers[0]
        self.votes(*[(p, target) for p in self.players if p != target])
        game = advance(self.game)
        self.assertEqual(game.phase, Phase.VOTE_RESULT)
        target.refresh_from_db()
        self.assertFalse(target.is_alive)

    def test_eliminating_the_last_wolf_ends_the_game(self):
        self.kill(self.wolves[0])
        last = self.wolves[1]
        self.votes(*[(p, last) for p in self.players if p.is_alive and p != last])
        game = advance(self.game)
        self.assertEqual((game.phase, game.winner), (Phase.GAME_OVER, "VILLAGE"))
        self.assertIn("Victoire du village", self.last_announcement())
