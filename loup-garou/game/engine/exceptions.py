class EngineError(Exception):
    """Erreur levée par le moteur de jeu."""


class InvalidAction(EngineError):
    """Action refusée par l'arbitre (la future API la traduira en 400)."""


class PhaseConflict(EngineError):
    """La partie n'est plus dans la phase attendue : quelqu'un l'a déjà fait avancer."""
