"""State machine : enchaînement des phases et conditions de victoire.

Cycle :
    Nuit : NIGHT_SEER → NIGHT_WOLVES → NIGHT_WITCH
    Jour : DAWN → DAY_DEBATE → DAY_VOTE → VOTE_RESULT
    puis NIGHT_SEER du cycle suivant. GAME_OVER est terminal.

Les conditions de victoire sont vérifiées à chaque transition.
"""

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from game.models import Game, GameStatus, Phase, Role, Winner

from . import announcements, resolution
from .exceptions import PhaseConflict
from .rules import phase_deadline

TRANSITIONS = {
    Phase.NIGHT_SEER: Phase.NIGHT_WOLVES,
    Phase.NIGHT_WOLVES: Phase.NIGHT_WITCH,
    Phase.NIGHT_WITCH: Phase.DAWN,
    Phase.DAWN: Phase.DAY_DEBATE,
    Phase.DAY_DEBATE: Phase.DAY_VOTE,
    Phase.DAY_VOTE: Phase.VOTE_RESULT,
    Phase.VOTE_RESULT: Phase.NIGHT_SEER,
}


def _alive(players, role):
    return [p for p in players if p.is_alive and p.role == role]


def is_phase_playable(phase, players):
    """Une phase de nuit est sautée automatiquement quand personne ne peut y agir.

    - Voyante : sautée si elle est morte.
    - Sorcière : sautée si elle est morte ou n'a plus aucune potion.
      Les morts de la nuit ne sont appliquées qu'à l'aube : une sorcière
      ciblée par les loups cette nuit est encore vivante pendant NIGHT_WITCH
      et joue, ce qui lui permet de se sauver avec sa potion de vie.
    """
    if phase == Phase.NIGHT_SEER:
        return bool(_alive(players, Role.SEER))
    if phase == Phase.NIGHT_WOLVES:
        return bool(_alive(players, Role.WEREWOLF))
    if phase == Phase.NIGHT_WITCH:
        return any(w.has_life_potion or w.has_death_potion for w in _alive(players, Role.WITCH))
    return True


def next_phase(current, players):
    """Phase suivant ``current`` en sautant les phases de nuit injouables."""
    if current not in TRANSITIONS:
        raise PhaseConflict(f"Aucune transition depuis {current}.")
    candidate = TRANSITIONS[current]
    while not is_phase_playable(candidate, players):
        candidate = TRANSITIONS[candidate]
    return candidate


def check_winner(players):
    """Loups vivants == 0 → village ; loups vivants ≥ non-loups vivants → loups.

    Les non-loups (« humains ») sont les villageois, la voyante et la sorcière.
    """
    alive = [p for p in players if p.is_alive]
    wolves = sum(1 for p in alive if p.role == Role.WEREWOLF)
    humans = len(alive) - wolves
    if wolves == 0:
        return Winner.VILLAGE
    if wolves >= humans:
        return Winner.WOLVES
    return None


def advance(game, expected_phase=None):
    """Fait passer la partie à la phase suivante et renvoie la partie à jour.

    - En quittant DAY_VOTE, le vote est résolu (le résultat s'affiche pendant
      VOTE_RESULT).
    - En entrant dans DAWN, la nuit est résolue.
    - Après chaque résolution comme à chaque transition, la victoire est
      vérifiée : la partie passe directement en GAME_OVER si un camp a gagné.

    ``expected_phase`` protège contre une double avance (thread IA + timer +
    action humaine) : si la partie a déjà bougé, ``PhaseConflict`` est levée et
    rien n'est écrit. L'écriture finale est un compare-and-swap sur
    ``(phase, version)``.
    """
    with transaction.atomic():
        game = Game.objects.get(pk=game.pk)
        current, version = game.phase, game.version
        if game.status == GameStatus.FINISHED:
            raise PhaseConflict("La partie est terminée.")
        if expected_phase is not None and current != expected_phase:
            raise PhaseConflict(f"Phase attendue {expected_phase}, phase réelle {current}.")

        if current == Phase.DAY_VOTE:
            resolution.resolve_vote(game)
        players = list(game.players.all())
        target = next_phase(current, players)
        if target == Phase.DAWN:
            resolution.resolve_night(game)
            players = list(game.players.all())

        now = timezone.now()
        updates = {"phase_started_at": now, "updated_at": now, "version": version + 1}
        winner = check_winner(players)
        if winner is not None:
            updates.update(
                phase=Phase.GAME_OVER,
                status=GameStatus.FINISHED,
                winner=winner,
                phase_deadline=None,
            )
        else:
            updates.update(phase=target, phase_deadline=phase_deadline(target, now))
            if current == Phase.VOTE_RESULT:
                updates["day_number"] = F("day_number") + 1

        updated = Game.objects.filter(pk=game.pk, phase=current, version=version).update(**updates)
        if updated != 1:
            raise PhaseConflict("La partie a été modifiée pendant la transition.")

        new_day = game.day_number + 1 if "day_number" in updates else game.day_number
        announcements.on_enter(game, current, updates["phase"], new_day, winner)

    game.refresh_from_db()
    return game


def advance_if_expired(game, now=None):
    """Avance la partie si le timer de sa phase est écoulé.

    Renvoie True si la partie a avancé. Pas d'action enregistrée = abstention
    (jour) ou aucune action (nuit), ce que la résolution interprète.
    """
    if game.is_finished or not game.is_expired(now):
        return False
    try:
        advance(game, expected_phase=game.phase)
    except PhaseConflict:
        return False
    return True
