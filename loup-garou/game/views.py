import json

from django.conf import settings
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from game.engine import (
    InvalidAction,
    create_game,
    player_view,
    submit_message,
    submit_seer_inspection,
    submit_vote,
    submit_witch_decision,
    submit_wolf_target,
)
from game.models import Channel, Game
from game.presenters import ROLE_BY_KEY, board_context, status_phase
from game.services.game_loop import tick, wake_agents
from game.services.retention import purge_expired_games

SESSION_GAME_KEY = "game_id"


# --------------------------------------------------------------------------- #
#  Session : une partie par navigateur, sans compte utilisateur (MVP).        #
# --------------------------------------------------------------------------- #

def _session_key(request):
    if not request.session.session_key:
        request.session.save()
    return request.session.session_key


def _current_game(request):
    """Partie de la session et son joueur humain, ou (None, None)."""
    game_id = request.session.get(SESSION_GAME_KEY)
    game = Game.objects.filter(pk=game_id).first() if game_id else None
    if game is None:
        request.session.pop(SESSION_GAME_KEY, None)
        return None, None
    return game, game.players.get(is_human=True)


# --------------------------------------------------------------------------- #
#  Pages                                                                      #
# --------------------------------------------------------------------------- #

def _start_page(request, *, error=None, name="", status=200):
    return render(
        request,
        "game/start.html",
        {
            "error": error,
            "name": name,
            "debug_roles": list(ROLE_BY_KEY) if settings.DEBUG else [],
            "selected_role": request.GET.get("role") or request.POST.get("role") or "",
        },
        status=status,
    )


@require_GET
def village_view(request):
    """Écran de départ sans partie en cours, sinon le plateau de la partie."""
    game, human = _current_game(request)
    if game is None:
        return _start_page(request)
    game = tick(game)
    context = board_context(player_view(game, human))
    context["live_config"] = {
        "me_id": human.pk,
        "csrf_token": get_token(request),
        "poll_ms": 1500,
        "urls": {
            "state": reverse("game:api_state"),
            "message": reverse("game:api_message"),
            "vote": reverse("game:api_vote"),
            "night": reverse("game:api_night"),
        },
    }
    return render(request, "game/village.html", context)


@require_POST
def new_game_view(request):
    """Lance une partie : rôles tirés au hasard (``role`` forcé en DEBUG)."""
    name = request.POST.get("name", "")
    human_role = None
    if settings.DEBUG:
        human_role = ROLE_BY_KEY.get(request.POST.get("role", ""))
    purge_expired_games()  # conservation limitée (RGPD), sans tâche planifiée
    try:
        game = create_game(_session_key(request), name, human_role=human_role)
    except InvalidAction as error:
        return _start_page(request, error=str(error), name=name, status=400)
    request.session[SESSION_GAME_KEY] = str(game.pk)
    return redirect("game:village")


@require_POST
def leave_game_view(request):
    """Quitte la partie en cours : retour à l'écran de départ."""
    request.session.pop(SESSION_GAME_KEY, None)
    return redirect("game:village")


# --------------------------------------------------------------------------- #
#  Données personnelles (RGPD)                                                #
# --------------------------------------------------------------------------- #

@require_GET
def privacy_view(request):
    """Information des joueurs (RGPD art. 13 et AI Act art. 50)."""
    session_key = request.session.session_key
    return render(
        request,
        "game/privacy.html",
        {
            "controller": settings.PRIVACY_CONTROLLER,
            "contact": settings.PRIVACY_CONTACT,
            "hosting": settings.PRIVACY_HOSTING,
            "retention_days": settings.GAME_RETENTION_DAYS,
            "stored_games": Game.objects.filter(session_key=session_key).count() if session_key else 0,
            "deleted": request.GET.get("supprime") == "1",
        },
    )


@require_POST
def delete_data_view(request):
    """Droit à l'effacement : supprime toutes les parties de ce navigateur.

    Messages, votes, actions de nuit et journaux IA partent en cascade ; la
    session est ensuite détruite (nouveau cookie, ancienne ligne effacée).
    """
    if request.POST.get("confirm") != "1":
        return redirect("game:privacy")
    session_key = request.session.session_key
    if session_key:
        Game.objects.filter(session_key=session_key).delete()
    request.session.flush()
    return redirect(reverse("game:privacy") + "?supprime=1")


# --------------------------------------------------------------------------- #
#  API JSON (polling du front)                                                #
# --------------------------------------------------------------------------- #

def _error(message, status=400):
    return JsonResponse({"error": message}, status=status)


def _json_body(request):
    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise InvalidAction("Requête JSON invalide.") from None
    if not isinstance(body, dict):
        raise InvalidAction("Requête JSON invalide.")
    return body


def api_view(handler):
    """Résout la partie de la session et traduit les refus du moteur en 400."""

    def wrapper(request):
        game, human = _current_game(request)
        if game is None:
            return _error("Aucune partie en cours.", status=404)
        try:
            response = handler(request, game, human)
        except InvalidAction as error:
            return _error(str(error))
        if request.method == "POST":
            wake_agents(game)  # les IA réagissent tout de suite à l'action humaine
        return response

    wrapper.__name__ = handler.__name__
    wrapper.__doc__ = handler.__doc__
    return wrapper


@require_GET
@api_view
def state_view(request, game, human):
    """État de la partie vu par l'humain ; ``?since=<id>`` = messages après cet id."""
    try:
        since = max(int(request.GET.get("since", 0)), 0)
    except ValueError:
        since = 0
    game = tick(game)
    view = player_view(game, human, since_id=since)
    view["display"] = status_phase(view)
    return JsonResponse(view)


@require_POST
@api_view
def message_view(request, game, human):
    """Message dans le canal public (jour) ou celui des loups (nuit)."""
    body = _json_body(request)
    channel = body.get("channel", Channel.PUBLIC)
    if channel not in Channel.values:
        raise InvalidAction("Canal inconnu.")
    text = body.get("text")
    if not isinstance(text, str):
        raise InvalidAction("Le message doit être un texte.")
    message = submit_message(game, human, text, channel)
    return JsonResponse({"ok": True, "message_id": message.pk})


@require_POST
@api_view
def vote_view(request, game, human):
    """Vote de jour ; ``target_id`` absent ou null = vote blanc."""
    body = _json_body(request)
    vote = submit_vote(game, human, body.get("target_id"))
    return JsonResponse({"ok": True, "target_id": vote.target_id})


@require_POST
@api_view
def night_view(request, game, human):
    """Action de nuit : ``seer`` / ``wolf`` (``target_id``) ou ``witch``
    (``heal`` booléen, ``kill_target_id`` facultatif)."""
    body = _json_body(request)
    action = body.get("action")
    if action == "seer":
        inspection = submit_seer_inspection(game, human, body.get("target_id"))
        return JsonResponse(
            {
                "ok": True,
                "target_id": inspection.target_id,
                "target_name": inspection.target.name,
                "role": inspection.revealed_role,
                "role_label": inspection.get_revealed_role_display(),
            }
        )
    if action == "wolf":
        choice = submit_wolf_target(game, human, body.get("target_id"))
        return JsonResponse({"ok": True, "target_id": choice.target_id})
    if action == "witch":
        heal = body.get("heal", False)
        if not isinstance(heal, bool):
            raise InvalidAction("« heal » doit être un booléen.")
        actions = submit_witch_decision(
            game, human, heal=heal, kill_target=body.get("kill_target_id")
        )
        return JsonResponse({"ok": True, "actions": [a.action_type for a in actions]})
    raise InvalidAction("Action de nuit inconnue (seer, wolf ou witch).")
