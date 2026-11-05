"""Boucle de jeu déclenchée par le polling du front."""

from game.engine import try_advance


def tick(game):
    """Fait avancer la partie si sa phase est terminée, puis la renvoie à jour.

    Appelé à chaque requête de polling : la phase avance quand son timer est
    écoulé ou quand tous les joueurs attendus ont agi. L'orchestrateur des IA
    s'y branchera (étape 4). Comme l'état est en base, un redémarrage du
    serveur reprend la partie au polling suivant.
    """
    try_advance(game)
    game.refresh_from_db()
    return game
