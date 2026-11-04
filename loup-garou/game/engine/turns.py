"""Gestion des tours : qui doit agir dans la phase en cours, et quand elle est finie.

Une phase se termine :
- dès que tous les joueurs attendus ont agi (phases d'action) ;
- ou à l'expiration de son timer (toutes les phases).

DAWN, DAY_DEBATE et VOTE_RESULT n'attendent personne : elles avancent au timer,
ou plus tôt sur un appel explicite à ``advance`` (par l'orchestrateur IA pour
clore le débat, par exemple).
"""

from game.models import Phase, Role
from night_time.models import NightAction, NightActionType
from voting.models import Vote

from .exceptions import PhaseConflict
from .state_machine import advance

ACTING_ROLE = {
    Phase.NIGHT_SEER: Role.SEER,
    Phase.NIGHT_WOLVES: Role.WEREWOLF,
    Phase.NIGHT_WITCH: Role.WITCH,
}

# Actions qui closent le tour de chaque rôle de nuit. La sorcière enregistre
# sa décision complète en une fois (soin, poison, les deux, ou WITCH_PASS).
CLOSING_ACTIONS = {
    Phase.NIGHT_SEER: [NightActionType.SEER_INSPECT],
    Phase.NIGHT_WOLVES: [NightActionType.WOLF_TARGET],
    Phase.NIGHT_WITCH: [
        NightActionType.WITCH_HEAL,
        NightActionType.WITCH_KILL,
        NightActionType.WITCH_PASS,
    ],
}


def expected_actors(game):
    """Joueurs vivants qui doivent agir dans la phase en cours."""
    alive = game.players.filter(is_alive=True)
    if game.phase in ACTING_ROLE:
        return list(alive.filter(role=ACTING_ROLE[game.phase]))
    if game.phase == Phase.DAY_VOTE:
        return list(alive)
    return []


def _acted_ids(game):
    if game.phase in CLOSING_ACTIONS:
        return set(
            NightAction.objects.filter(
                game=game,
                night_number=game.day_number,
                action_type__in=CLOSING_ACTIONS[game.phase],
            ).values_list("actor_id", flat=True)
        )
    if game.phase == Phase.DAY_VOTE:
        return set(
            Vote.objects.filter(game=game, day_number=game.day_number).values_list(
                "voter_id", flat=True
            )
        )
    return set()


def pending_actors(game):
    """Joueurs attendus qui n'ont pas encore agi."""
    acted = _acted_ids(game)
    return [p for p in expected_actors(game) if p.id not in acted]


def is_phase_complete(game):
    """Vrai si la phase attend des joueurs et qu'ils ont tous agi."""
    expected = expected_actors(game)
    return bool(expected) and not pending_actors(game)


def try_advance(game, now=None):
    """Avance la partie si la phase est complète ou si son timer est écoulé.

    À appeler après chaque action enregistrée et à chaque tick du timer.
    Renvoie True si la partie a avancé ; False si elle doit encore attendre
    ou si un autre appel l'a déjà fait avancer.
    """
    if game.is_finished:
        return False
    if not (is_phase_complete(game) or game.is_expired(now)):
        return False
    try:
        advance(game, expected_phase=game.phase)
    except PhaseConflict:
        return False
    return True
