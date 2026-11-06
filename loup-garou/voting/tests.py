from django.db import IntegrityError, transaction
from django.test import TestCase

from game.models import Game, Personality, Player, Role
from voting.models import Vote


class VoteModelTests(TestCase):
    def setUp(self):
        self.game = Game.objects.create(session_key="s1")
        self.alice = self.add_player(0, "Alice", Role.WEREWOLF)
        self.bob = self.add_player(1, "Bob", Role.WEREWOLF)
        self.carol = self.add_player(2, "Carol", Role.VILLAGER)

    def add_player(self, seat, name, role):
        return Player.objects.create(
            game=self.game, seat=seat, name=name, role=role,
            personality=Personality.IMPULSIF,
        )

    def vote(self, voter, target, day=1):
        return Vote.objects.create(game=self.game, day_number=day, voter=voter, target=target)

    def assertRejected(self, *args, **kwargs):
        with transaction.atomic(), self.assertRaises(IntegrityError):
            self.vote(*args, **kwargs)

    def test_vote_against_another_player(self):
        vote = self.vote(self.alice, self.carol)
        self.assertFalse(vote.is_abstention)
        self.assertEqual(self.carol.votes_received.get(), vote)

    def test_null_target_is_an_abstention(self):
        self.assertTrue(self.vote(self.alice, None).is_abstention)

    def test_wolf_can_vote_against_wolf_by_day(self):
        self.vote(self.alice, self.bob)

    def test_vote_against_self_is_rejected(self):
        self.assertRejected(self.alice, self.alice)

    def test_second_vote_same_day_is_rejected(self):
        self.vote(self.alice, self.carol)
        self.assertRejected(self.alice, self.bob)

    def test_one_vote_per_day(self):
        self.vote(self.alice, self.carol, day=1)
        self.vote(self.alice, self.carol, day=2)
        self.assertEqual(self.alice.votes_cast.count(), 2)

    def test_day_zero_is_rejected(self):
        self.assertRejected(self.alice, self.carol, day=0)
