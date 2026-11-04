"""Création d'une partie et tirage aléatoire des rôles."""

import random

from django.db import transaction
from django.utils import timezone

from game.models import Game, Personality, Phase, Player, Role, new_seed

from .exceptions import InvalidAction
from .rules import AI_NAMES, HUMAN_NAME_MAX_LENGTH, ROLE_COMPOSITION, phase_deadline


def _clean_human_name(name):
    name = (name or "").strip()
    if not name:
        raise InvalidAction("Le nom du joueur est obligatoire.")
    if len(name) > HUMAN_NAME_MAX_LENGTH:
        raise InvalidAction(f"Le nom ne doit pas dépasser {HUMAN_NAME_MAX_LENGTH} caractères.")
    return name


def draw_players(human_name, player_count, rng):
    """Tire les places, rôles, noms et personnalités, sans toucher à la base.

    Renvoie une liste de dicts triée par siège ; même ``rng`` → même tirage.
    """
    composition = ROLE_COMPOSITION[player_count]
    roles = [role for role, count in composition.items() for _ in range(count)]
    rng.shuffle(roles)

    human_seat = rng.randrange(player_count)
    taken = human_name.casefold()
    names = rng.sample([n for n in AI_NAMES if n.casefold() != taken], player_count - 1)
    personalities = list(Personality.values)
    rng.shuffle(personalities)

    players = []
    ai_index = 0
    for seat, role in enumerate(roles):
        is_witch = role == Role.WITCH
        if seat == human_seat:
            name, personality = human_name, None
        else:
            name = names[ai_index]
            personality = personalities[ai_index % len(personalities)]
            ai_index += 1
        players.append(
            {
                "seat": seat,
                "name": name,
                "is_human": seat == human_seat,
                "role": role,
                "personality": personality,
                "has_life_potion": is_witch,
                "has_death_potion": is_witch,
            }
        )
    return players


def create_game(session_key, human_name, seed=None, player_count=7):
    """Crée une partie, tire les rôles (humain compris) et ouvre la première nuit."""
    if player_count not in ROLE_COMPOSITION:
        raise InvalidAction(f"Parties à {player_count} joueurs non prises en charge.")
    human_name = _clean_human_name(human_name)
    if seed is None:
        seed = new_seed()

    drawn = draw_players(human_name, player_count, random.Random(seed))
    now = timezone.now()
    with transaction.atomic():
        # La voyante est forcément vivante au début : la nuit commence par elle.
        game = Game.objects.create(
            session_key=session_key,
            seed=seed,
            phase=Phase.NIGHT_SEER,
            phase_started_at=now,
            phase_deadline=phase_deadline(Phase.NIGHT_SEER, now),
        )
        Player.objects.bulk_create(Player(game=game, **p) for p in drawn)
    return game
