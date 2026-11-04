"""Constantes de règles du jeu."""

from datetime import timedelta

from game.models import Phase, Role

# Composition par nombre de joueurs ; 8 à 12 joueurs viendront après le MVP.
ROLE_COMPOSITION = {
    7: {Role.WEREWOLF: 2, Role.VILLAGER: 3, Role.SEER: 1, Role.WITCH: 1},
}

# Réservoir de noms pour les IA (les 6 premiers sont ceux du plateau du front).
AI_NAMES = [
    "Victor", "Chloé", "Lucas", "Léa", "Thomas", "Marc",
    "Inès", "Hugo", "Camille", "Jules", "Zoé", "Margaux",
]

HUMAN_NAME_MAX_LENGTH = 32

# Durée de chaque phase avant que le timer ne fasse avancer la partie.
# Toutes les phases non terminales ont une échéance : la partie ne peut pas se bloquer.
PHASE_TIMEOUT = timedelta(seconds=45)
PHASE_DURATIONS = {
    Phase.NIGHT_SEER: PHASE_TIMEOUT,
    Phase.NIGHT_WOLVES: PHASE_TIMEOUT,
    Phase.NIGHT_WITCH: PHASE_TIMEOUT,
    Phase.DAWN: timedelta(seconds=8),
    Phase.DAY_DEBATE: PHASE_TIMEOUT,
    Phase.DAY_VOTE: PHASE_TIMEOUT,
    Phase.GAME_OVER: None,
}


def phase_deadline(phase, now):
    duration = PHASE_DURATIONS[phase]
    return now + duration if duration is not None else None
