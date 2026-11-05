"""Orchestrateur des tours IA : fait parler, voter et agir les agents.

``schedule(game)`` est appelé à chaque polling (``tick``) et après chaque
action humaine. Il regarde la phase en cours et lance, en arrière-plan, le
travail des IA qui n'a pas encore été fait :

- NIGHT_SEER / NIGHT_WITCH : la voyante ou la sorcière IA décide ;
- NIGHT_WOLVES : deux loups IA → le premier choisit, le second s'aligne ;
  loup humain → son compère IA propose une cible dans le canal secret,
  répond à chacun de ses messages, et s'aligne sur son choix (moteur) ;
- DAY_DEBATE : salves de 1 à 2 IA (les joueurs nommés par l'humain d'abord,
  puis ceux qui ont le moins parlé), et réponse à chaque message humain ;
- DAY_VOTE : chaque IA vote.

Toutes les écritures passent par les actions validées du moteur : si la phase
a changé entre-temps, l'action est refusée et simplement ignorée. Comme l'état
est en base, un redémarrage du serveur reprend au polling suivant.
"""

import logging
import random
import threading
import time

from django.conf import settings
from django.db import connections
from django.db.models import Count

from game.engine import (
    InvalidAction,
    pending_actors,
    submit_message,
    submit_seer_inspection,
    submit_vote,
    submit_witch_decision,
    submit_wolf_target,
)
from game.models import Channel, Game, Message, MessageKind, Phase, Role

from .decisions import decide
from .prompts import DecisionType

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_running = set()  # tâches en cours, par clé
_done = set()  # tâches terminées, pour ne jamais les rejouer dans la même phase
_call_slots = None
_last_call_at = [0.0]


# --------------------------------------------------------------------------- #
#  Réglages                                                                   #
# --------------------------------------------------------------------------- #

def _setting(name, default):
    return getattr(settings, name, default)


def _slots():
    global _call_slots
    if _call_slots is None:
        _call_slots = threading.BoundedSemaphore(_setting("AI_MAX_CONCURRENT_CALLS", 2))
    return _call_slots


def _pause(seconds):
    if seconds > 0 and not _setting("AI_RUN_INLINE", False):
        time.sleep(seconds)


MIN_CALL_INTERVAL = 0.25  # secondes entre deux départs d'appel Mistral


def _decide(game, player, decision_type):
    """Décision IA sous limite de débit : peu d'appels simultanés, légèrement espacés."""
    with _slots():
        if not _setting("AI_RUN_INLINE", False):
            with _lock:
                now = time.monotonic()
                start = max(now, _last_call_at[0] + MIN_CALL_INTERVAL)
                _last_call_at[0] = start
            _pause(start - now)
        return decide(game, player, decision_type)


# --------------------------------------------------------------------------- #
#  Lancement des tâches                                                       #
# --------------------------------------------------------------------------- #

def _launch(key, job, game_id):
    """Lance ``job`` une seule fois par clé ; renvoie False s'il tourne ou a tourné."""
    with _lock:
        if key in _running or key in _done:
            return False
        _running.add(key)

    def run():
        try:
            job(game_id)
        except Exception:
            logger.exception("Tâche IA %s en échec", key)
        finally:
            with _lock:
                _running.discard(key)
                _done.add(key)
        try:
            # Enchaîne : la phase a pu avancer et attendre d'autres IA.
            schedule(Game.objects.get(pk=game_id))
        except Exception:
            logger.exception("Relance de l'orchestrateur impossible après %s", key)
        finally:
            if not _setting("AI_RUN_INLINE", False):
                connections.close_all()  # connexion propre au thread

    if _setting("AI_RUN_INLINE", False):
        run()
    else:
        threading.Thread(target=run, name=f"ia-{key}", daemon=True).start()
    return True


def _is_running(prefix):
    with _lock:
        return any(key.startswith(prefix) for key in _running)


def reset():
    """Oublie les tâches mémorisées (tests)."""
    with _lock:
        _running.clear()
        _done.clear()
        _last_call_at[0] = 0.0


def _phase_key(game, name):
    return f"{game.pk}:{game.version}:{name}"


def _still(game_id, version):
    """Relit la partie ; None si elle a changé de phase entre-temps."""
    game = Game.objects.get(pk=game_id)
    return game if game.version == version and not game.is_finished else None


def schedule(game):
    """Lance le travail IA de la phase en cours qui n'a pas encore été fait."""
    if not _setting("AI_ORCHESTRATOR", True):
        return
    game.refresh_from_db()
    if game.is_finished:
        return
    planner = PLANNERS.get(game.phase)
    if planner:
        planner(game)


# --------------------------------------------------------------------------- #
#  Nuit                                                                       #
# --------------------------------------------------------------------------- #

def _pending_ai(game):
    return [p for p in pending_actors(game) if not p.is_human]


def _plan_seer(game):
    if _pending_ai(game):
        _launch(_phase_key(game, "seer"), _seer_job(game.version), game.pk)


def _seer_job(version):
    def job(game_id):
        game = _still(game_id, version)
        for seer in _pending_ai(game) if game else []:
            decision = _decide(game, seer, DecisionType.SEER_INSPECT)
            _safely(submit_seer_inspection, game, seer, decision.target_id)
    return job


def _plan_witch(game):
    if _pending_ai(game):
        _launch(_phase_key(game, "witch"), _witch_job(game.version), game.pk)


def _witch_job(version):
    def job(game_id):
        game = _still(game_id, version)
        for witch in _pending_ai(game) if game else []:
            decision = _decide(game, witch, DecisionType.WITCH_DECISION)
            _safely(
                submit_witch_decision, game, witch,
                heal=decision.heal, kill_target=decision.kill_target_id,
            )
    return job


def _plan_wolves(game):
    wolves = list(game.players.filter(role=Role.WEREWOLF, is_alive=True))
    ai_wolves = [w for w in wolves if not w.is_human]
    if not ai_wolves:
        return
    human_wolf = next((w for w in wolves if w.is_human), None)
    if human_wolf is None:
        if _pending_ai(game):
            _launch(_phase_key(game, "wolves"), _wolves_job(game.version), game.pk)
        return

    # Loup humain : proposition d'ouverture, puis une réponse par message humain.
    _launch(_phase_key(game, "wolf-proposal"), _wolf_talk_job(game.version), game.pk)
    last = (
        game.messages.filter(channel=Channel.WOLVES, author=human_wolf, day_number=game.day_number)
        .order_by("-id")
        .first()
    )
    if last and not _is_running(f"{game.pk}:{game.version}:wolf-"):
        _launch(_phase_key(game, f"wolf-reply-{last.pk}"), _wolf_talk_job(game.version), game.pk)


def _wolves_job(version):
    """Deux loups IA : le premier décide, les autres s'alignent (pas d'appel en plus)."""
    def job(game_id):
        game = _still(game_id, version)
        pending = _pending_ai(game) if game else []
        if not pending:
            return
        leader = pending[0]
        decision = _decide(game, leader, DecisionType.WOLF_TARGET)
        if decision.message:
            _safely(submit_message, game, leader, decision.message, Channel.WOLVES)
        for wolf in pending:
            _safely(submit_wolf_target, game, wolf, decision.target_id)
    return job


def _wolf_talk_job(version):
    """Compère IA d'un loup humain : parle dans le canal secret et propose une cible."""
    def job(game_id):
        game = _still(game_id, version)
        if game is None:
            return
        partner = game.players.filter(role=Role.WEREWOLF, is_alive=True, is_human=False).first()
        if partner is None:
            return
        decision = _decide(game, partner, DecisionType.WOLF_TARGET)
        if decision.message:
            _safely(submit_message, game, partner, decision.message, Channel.WOLVES)
        # Proposition retenue si l'humain ne choisit pas. S'il a déjà choisi,
        # le moteur a aligné le compère et la phase a avancé : rien à faire.
        if _still(game_id, version):
            _safely(submit_wolf_target, game, partner, decision.target_id)
    return job


# --------------------------------------------------------------------------- #
#  Jour                                                                       #
# --------------------------------------------------------------------------- #

def _debate_messages(game):
    return Message.objects.filter(
        game=game,
        kind=MessageKind.CHAT,
        channel=Channel.PUBLIC,
        day_number=game.day_number,
    )


def pick_speakers(game, count, text="", rng=random):
    """IA vivantes qui prennent la parole : celles nommées dans ``text`` d'abord,
    puis celles qui ont le moins parlé aujourd'hui."""
    spoken = dict(
        _debate_messages(game).values_list("author").annotate(n=Count("id")).values_list("author", "n")
    )
    candidates = list(game.players.filter(is_alive=True, is_human=False))
    rng.shuffle(candidates)
    named = [p for p in candidates if text and p.name.casefold() in text.casefold()]
    others = sorted((p for p in candidates if p not in named), key=lambda p: spoken.get(p.pk, 0))
    return (named + others)[:count]


def _plan_debate(game):
    if _is_running(f"{game.pk}:{game.version}:debate"):
        return
    messages = _debate_messages(game)
    last_human = messages.filter(author__is_human=True).order_by("-id").first()
    if last_human and not messages.filter(id__gt=last_human.id, author__is_human=False).exists():
        key = _phase_key(game, f"debate-reply-{last_human.pk}")
        if _launch(key, _debate_job(game.version, last_human.content), game.pk):
            return

    phase_messages = messages.filter(phase=Phase.DAY_DEBATE)
    spontaneous = phase_messages.filter(author__is_human=False).count()
    if spontaneous >= _setting("AI_DEBATE_MAX_MESSAGES", 8):
        return
    last = game.messages.filter(day_number=game.day_number).order_by("-id").first()
    gap = _setting("AI_DEBATE_GAP", 4.0)
    if last and (time.time() - last.created_at.timestamp()) < gap:
        return
    _launch(_phase_key(game, f"debate-salvo-{spontaneous}"), _debate_job(game.version), game.pk)


def _debate_job(version, reply_to=""):
    def job(game_id):
        game = _still(game_id, version)
        if game is None:
            return
        speakers = pick_speakers(game, random.choice((1, 2)), reply_to)
        for i, speaker in enumerate(speakers):
            if i:
                _pause(_setting("AI_PACING", 0.8))
            game = _still(game_id, version)
            if game is None:
                return
            decision = _decide(game, speaker, DecisionType.DAY_CHAT)
            _safely(submit_message, game, speaker, decision.message)
    return job


def _plan_vote(game):
    if _pending_ai(game):
        _launch(_phase_key(game, "votes"), _vote_job(game.version), game.pk)


def _vote_job(version):
    def job(game_id):
        game = _still(game_id, version)
        for voter in _pending_ai(game) if game else []:
            game = _still(game_id, version)
            if game is None:
                return
            decision = _decide(game, voter, DecisionType.DAY_VOTE)
            _safely(submit_vote, game, voter, decision.target_id)
    return job


def _safely(action, *args, **kwargs):
    """Applique une action IA ; un refus (phase déjà passée…) est simplement ignoré."""
    try:
        return action(*args, **kwargs)
    except InvalidAction as error:
        logger.info("Action IA ignorée (%s) : %s", action.__name__, error)
        return None


PLANNERS = {
    Phase.NIGHT_SEER: _plan_seer,
    Phase.NIGHT_WOLVES: _plan_wolves,
    Phase.NIGHT_WITCH: _plan_witch,
    Phase.DAY_DEBATE: _plan_debate,
    Phase.DAY_VOTE: _plan_vote,
}

__all__ = ["pick_speakers", "reset", "schedule"]
