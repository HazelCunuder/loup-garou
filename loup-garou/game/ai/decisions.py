"""Décision d'un agent IA : toujours une action légale, même si Mistral échoue.

``decide`` construit la mémoire de l'agent (vue autorisée), lui demande sa
décision, la valide selon les règles, et bascule sur un repli procédural
typé par la personnalité en cas d'échec (délai, erreur, sortie invalide ou
action illégale). Elle n'écrit pas l'action en base : c'est le rôle de
l'orchestrateur, via les actions validées du moteur.
"""

import logging
import os
import random
import re
from dataclasses import dataclass

from asgiref.sync import async_to_sync

from game.engine import player_view
from game.engine.rules import AI_NAMES
from game.models import Player
from game.services.mistral_client import MistralGameClient, MistralResponseError

from .context import build_context
from .personas import FallbackKind, get_persona
from .prompts import ACTIONS, MESSAGE_MAX_LENGTH, DecisionType, call_type, instructions, legal_targets

logger = logging.getLogger(__name__)

THOUGHT_MAX_LENGTH = 300
FALLBACK_KINDS = {
    DecisionType.DAY_CHAT: FallbackKind.CHAT,
    DecisionType.DAY_VOTE: FallbackKind.VOTE,
    DecisionType.WOLF_TARGET: FallbackKind.NIGHT,
}


# Noms qui ne doivent apparaître dans une réplique que s'ils jouent dans la
# partie : la réserve des IA et les noms fictifs des exemples de personnages.
KNOWN_NAMES = frozenset(AI_NAMES) | {"Nina", "Paul", "Basile"}


class InvalidDecision(MistralResponseError):
    """Réponse bien formée mais contraire aux règles (journalisée INVALID_OUTPUT)."""


def invented_names(message, view):
    """Noms connus cités dans ``message`` alors qu'ils ne jouent pas dans la partie."""
    in_game = {p["name"] for p in view["players"]}
    return sorted(
        name
        for name in KNOWN_NAMES - in_game
        if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", message)
    )


@dataclass(frozen=True)
class AgentDecision:
    decision_type: DecisionType
    action: str
    target_id: int | None = None
    target_name: str | None = None
    message: str = ""
    thought: str = ""
    used_fallback: bool = False

    # Sorcière : soin de la victime et/ou poison sur ``target_id``.
    @property
    def heal(self):
        return self.action in ("soigner", "soigner_et_empoisonner")

    @property
    def kill_target_id(self):
        return self.target_id if self.action in ("empoisonner", "soigner_et_empoisonner") else None


def _clean(text, limit):
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _find(players, name):
    wanted = name.strip().casefold()
    return next((p for p in players if p["name"].casefold() == wanted), None)


def validate(raw, view, decision_type, persona):
    """Transforme la réponse brute en ``AgentDecision`` ou lève ``InvalidDecision``."""
    decision_type = DecisionType(decision_type)
    action = raw["action"].strip().lower()
    if action not in ACTIONS[decision_type]:
        raise InvalidDecision(f"Action « {action} » non autorisée pour {decision_type}.")

    message = _clean(raw["message"], MESSAGE_MAX_LENGTH)
    if persona.label.casefold() in message.casefold():
        raise InvalidDecision("Le message révèle le personnage de l'agent.")
    if decision_type == DecisionType.DAY_CHAT and not message:
        raise InvalidDecision("Une prise de parole ne peut pas être vide.")
    ghosts = invented_names(message, view)
    if ghosts:
        raise InvalidDecision(f"Le message cite des joueurs absents : {', '.join(ghosts)}.")

    target = None
    name = raw["target"].strip()
    needs_target = decision_type in (DecisionType.WOLF_TARGET, DecisionType.SEER_INSPECT) or action in (
        "empoisonner",
        "soigner_et_empoisonner",
    )
    if name and (needs_target or decision_type in (DecisionType.DAY_CHAT, DecisionType.DAY_VOTE)):
        target = _find(legal_targets(view, decision_type), name)
        if target is None:
            raise InvalidDecision(f"Cible illégale ou inconnue : « {name} ».")
    if needs_target and target is None:
        raise InvalidDecision("Cette décision exige une cible.")

    if decision_type == DecisionType.WITCH_DECISION:
        private = view["private"]
        victim = private.get("wolf_victim")
        heal = action in ("soigner", "soigner_et_empoisonner")
        if heal and (not private["potions"]["life"] or victim is None):
            raise InvalidDecision("Soin impossible : pas de victime ou potion de vie utilisée.")
        if target is not None and not private["potions"]["death"]:
            raise InvalidDecision("Potion de mort déjà utilisée.")
        if heal and target is not None and target["id"] == victim["id"]:
            raise InvalidDecision("Impossible de soigner et d'empoisonner la même personne.")
        if action in ("rien", "soigner"):
            target = None
        message = ""

    return AgentDecision(
        decision_type=decision_type,
        action=action,
        target_id=target["id"] if target else None,
        target_name=target["name"] if target else None,
        message=message,
        thought=_clean(raw["thought"], THOUGHT_MAX_LENGTH),
    )


def fallback_decision(view, decision_type, persona, rng=random):
    """Repli procédural : action légale au hasard, dans le ton du personnage."""
    decision_type = DecisionType(decision_type)
    targets = legal_targets(view, decision_type)
    kind = FALLBACK_KINDS.get(decision_type)
    message = persona.fallback_line(kind, rng) if kind else ""
    target = None
    action = ACTIONS[decision_type][0]

    if decision_type == DecisionType.DAY_VOTE:
        if targets and rng.random() >= persona.abstain_rate:
            target = rng.choice(targets)
    elif decision_type in (DecisionType.WOLF_TARGET, DecisionType.SEER_INSPECT):
        target = rng.choice(targets) if targets else None
    elif decision_type == DecisionType.WITCH_DECISION:
        private = view["private"]
        victim = private.get("wolf_victim")
        # Prudence : la sorcière ne se sauve que si c'est elle la victime.
        if victim and victim["id"] == view["me"]["id"] and private["potions"]["life"]:
            action = "soigner"

    return AgentDecision(
        decision_type=decision_type,
        action=action,
        target_id=target["id"] if target else None,
        target_name=target["name"] if target else None,
        message=message,
        thought="Repli procédural.",
        used_fallback=True,
    )


_default_client = None


def default_client():
    """Client partagé ; ``AI_BACKEND=fake`` désactive Mistral (tests manuels hors ligne)."""
    global _default_client
    if os.getenv("AI_BACKEND", "").strip().lower() == "fake":
        return None
    if _default_client is None:
        _default_client = MistralGameClient()
    return _default_client


def decide(game, player, decision_type, *, client=None, rng=random):
    """Décision de l'agent ``player`` ; renvoie toujours une ``AgentDecision`` légale."""
    if player.is_human or player.personality is None:
        raise ValueError("Seuls les joueurs IA prennent des décisions automatiques.")
    # Relecture : la mémoire (pensée précédente, vie, potions) doit être à jour.
    game.refresh_from_db()
    player = Player.objects.get(pk=player.pk)
    decision_type = DecisionType(decision_type)
    persona = get_persona(player.personality)
    view = player_view(game, player)
    client = client if client is not None else default_client()

    decision = None
    if client is not None:
        try:
            decision = async_to_sync(client.get_agent_response)(
                game=game,
                player=player,
                call_type=call_type(decision_type),
                instructions=instructions(view, decision_type),
                context=build_context(view),
                validator=lambda raw: validate(raw, view, decision_type, persona),
            )
        except Exception:  # le jeu ne doit jamais bloquer sur l'IA
            logger.exception("Décision IA impossible pour %s", player.name)
    if decision is None:
        decision = fallback_decision(view, decision_type, persona, rng)

    Player.objects.filter(pk=player.pk).update(last_thought=decision.thought)
    return decision


__all__ = [
    "AgentDecision",
    "DecisionType",
    "InvalidDecision",
    "decide",
    "fallback_decision",
    "validate",
]
