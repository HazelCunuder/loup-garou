"""Boucle de jeu déclenchée par le polling du front."""

import logging

from game.engine import try_advance

logger = logging.getLogger(__name__)


def tick(game):
    """Fait avancer la partie si sa phase est terminée, puis la renvoie à jour.

    Appelé à chaque requête de polling : la phase avance quand son timer est
    écoulé ou quand tous les joueurs attendus ont agi ; l'orchestrateur lance
    ensuite le travail des IA de la phase. Comme l'état est en base, un
    redémarrage du serveur reprend la partie au polling suivant.
    """
    try_advance(game)
    game.refresh_from_db()
    wake_agents(game)
    return game


def wake_agents(game):
    """Relance les IA ; une panne de l'orchestrateur ne casse jamais la requête."""
    from game.ai.orchestrator import schedule

    try:
        schedule(game)
    except Exception:
        logger.exception("Orchestrateur IA en échec pour la partie %s", game.pk)
