"""Résolution de la nuit (à l'aube) et du vote (en entrant dans VOTE_RESULT).

Points d'extension appelés par la state machine. Ils ne font rien pour
l'instant afin que le squelette tourne de bout en bout ; les règles complètes
(consensus des loups, potions, égalité, abstentions…) arrivent en J2.
Ils s'exécutent dans la transaction de ``advance`` : toute écriture est annulée
si la transition échoue.
"""


def resolve_night(game):
    """Applique les actions de la nuit ``game.day_number`` et renvoie les morts."""
    return []


def resolve_vote(game):
    """Applique le vote du jour ``game.day_number`` et renvoie l'éliminé éventuel."""
    return None
