"""Vue autorisée d'un joueur (Fog of War).

Seule source de ce qu'un joueur a le droit de savoir : l'API la sert à
l'humain, la couche IA construit la mémoire des agents à partir d'elle.
"""

from django.utils import timezone

from game.models import Channel, Phase, Role
from night_time.models import NightAction, NightActionType
from voting.models import Vote

from .resolution import wolf_victim
from .turns import expected_actors, pending_actors

TURN_ACTION = {
    Phase.NIGHT_SEER: "seer",
    Phase.NIGHT_WOLVES: "wolf",
    Phase.NIGHT_WITCH: "witch",
    Phase.DAY_VOTE: "vote",
}


def _iso(value):
    return value.isoformat() if value else None


def known_roles(game, viewer, players):
    """Rôles que ``viewer`` connaît : le sien, les morts, ses compères loups,
    les joueurs qu'il a sondés (voyante), et tous en fin de partie."""
    known = {viewer.pk: viewer.role}
    for p in players:
        if not p.is_alive or game.is_finished:
            known[p.pk] = p.role
        elif viewer.role == Role.WEREWOLF and p.role == Role.WEREWOLF:
            known[p.pk] = p.role
    if viewer.role == Role.SEER:
        for target_id, role in NightAction.objects.filter(
            game=game, actor=viewer, action_type=NightActionType.SEER_INSPECT
        ).values_list("target_id", "revealed_role"):
            known.setdefault(target_id, role)
    return known


def _private(game, viewer, players):
    by_id = {p.pk: p for p in players}
    private = {"last_thought": viewer.last_thought}
    if viewer.role == Role.WEREWOLF:
        private["wolf_partners"] = [
            {"id": p.pk, "name": p.name, "is_alive": p.is_alive}
            for p in players
            if p.role == Role.WEREWOLF and p.pk != viewer.pk
        ]
    if viewer.role == Role.SEER:
        private["inspections"] = [
            {
                "night": a.night_number,
                "target_id": a.target_id,
                "target_name": by_id[a.target_id].name,
                "role": a.revealed_role,
                "role_label": Role(a.revealed_role).label,
            }
            for a in NightAction.objects.filter(
                game=game, actor=viewer, action_type=NightActionType.SEER_INSPECT
            ).order_by("night_number")
        ]
    if viewer.role == Role.WITCH:
        victim = wolf_victim(game) if game.phase == Phase.NIGHT_WITCH else None
        private["potions"] = {
            "life": viewer.has_life_potion,
            "death": viewer.has_death_potion,
        }
        private["wolf_victim"] = (
            {"id": victim.pk, "name": victim.name} if victim is not None else None
        )
    return private


def _turn(game, viewer):
    action = TURN_ACTION.get(game.phase)
    expected = viewer in expected_actors(game)
    return {
        "action": action if expected else None,
        "expected": expected,
        "done": expected and viewer not in pending_actors(game),
    }


def _votes(game, players):
    """Votes publics : les jours passés, et le jour courant une fois le vote clos."""
    by_id = {p.pk: p for p in players}
    votes = Vote.objects.filter(game=game, day_number__lt=game.day_number)
    if game.phase in (Phase.VOTE_RESULT, Phase.GAME_OVER):
        votes = Vote.objects.filter(game=game, day_number__lte=game.day_number)
    return [
        {
            "day": v.day_number,
            "voter_id": v.voter_id,
            "voter_name": by_id[v.voter_id].name,
            "target_id": v.target_id,
            "target_name": by_id[v.target_id].name if v.target_id else None,
        }
        for v in votes.order_by("day_number", "id")
    ]


def player_view(game, viewer, since_id=0):
    """Tout ce que ``viewer`` a le droit de savoir, en données JSON-sérialisables."""
    players = list(game.players.all())
    known = known_roles(game, viewer, players)

    channels = [Channel.PUBLIC]
    if viewer.role == Role.WEREWOLF:
        channels.append(Channel.WOLVES)
    messages = (
        game.messages.filter(channel__in=channels, id__gt=since_id)
        .select_related("author")
        .order_by("id")
    )

    return {
        "game": {
            "id": str(game.pk),
            "phase": game.phase,
            "phase_label": game.get_phase_display(),
            "day": game.day_number,
            "status": game.status,
            "winner": game.winner,
            "phase_started_at": _iso(game.phase_started_at),
            "phase_deadline": _iso(game.phase_deadline),
            "server_time": _iso(timezone.now()),
            "version": game.version,
        },
        "me": {
            "id": viewer.pk,
            "name": viewer.name,
            "role": viewer.role,
            "role_label": viewer.get_role_display(),
            "is_alive": viewer.is_alive,
            "is_human": viewer.is_human,
        },
        "players": [
            {
                "id": p.pk,
                "seat": p.seat,
                "name": p.name,
                "is_human": p.is_human,
                "is_me": p.pk == viewer.pk,
                "is_alive": p.is_alive,
                "role": known.get(p.pk),
                "role_label": Role(known[p.pk]).label if p.pk in known else None,
                "died_on_day": p.died_on_day,
                "death_cause": p.death_cause,
            }
            for p in players
        ],
        "messages": [
            {
                "id": m.id,
                "channel": m.channel,
                "kind": m.kind,
                "author_id": m.author_id,
                "author_name": m.author.name if m.author_id else None,
                # AI Act, art. 50 : tout texte écrit par une IA est signalé
                # comme tel, y compris de façon lisible par une machine.
                "author_is_ai": m.author_id is not None and not m.author.is_human,
                "content": m.content,
                "day": m.day_number,
                "phase": m.phase,
                "created_at": _iso(m.created_at),
            }
            for m in messages
        ],
        "votes": _votes(game, players),
        "private": _private(game, viewer, players),
        "turn": _turn(game, viewer),
    }
