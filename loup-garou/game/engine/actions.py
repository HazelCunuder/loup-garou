"""Actions des joueurs, validées par l'arbitre avant d'être enregistrées.

Chaque fonction relit la partie dans une transaction, vérifie la phase, l'acteur
et la cible, puis écrit l'action. Un refus lève ``InvalidAction`` (traduit en
400 par l'API). Une action qui peut clore un tour appelle ensuite
``try_advance`` : la phase avance dès que tous les joueurs attendus ont agi.
"""

from django.db import transaction

from game.models import Channel, Game, MessageKind, Message, Phase, Player, Role
from night_time.models import NightAction, NightActionType
from voting.models import Vote

from .exceptions import InvalidAction
from .resolution import wolf_victim
from .turns import try_advance

MESSAGE_MAX_LENGTH = 300
DAY_PHASES = (Phase.DAWN, Phase.DAY_DEBATE, Phase.DAY_VOTE, Phase.VOTE_RESULT)


def _load(game, player):
    """Relit la partie et le joueur, et vérifie qu'il peut agir."""
    game = Game.objects.get(pk=game.pk)
    player = Player.objects.get(pk=player.pk)
    if player.game_id != game.pk:
        raise InvalidAction("Ce joueur ne fait pas partie de la partie.")
    if game.is_finished:
        raise InvalidAction("La partie est terminée.")
    if not player.is_alive:
        raise InvalidAction("Les morts ne peuvent plus agir.")
    return game, player


def _require_phase(game, *phases):
    if game.phase not in phases:
        raise InvalidAction(f"Action impossible pendant la phase « {game.get_phase_display()} ».")


def _target(game, target, *, actor):
    """Résout la cible (Player ou id) et vérifie qu'elle est vivante et dans la partie."""
    if target is None:
        raise InvalidAction("Une cible est obligatoire.")
    target_id = getattr(target, "pk", target)
    try:
        target = Player.objects.get(pk=target_id, game=game)
    except (Player.DoesNotExist, ValueError, TypeError):
        raise InvalidAction("Cible inconnue.") from None
    if not target.is_alive:
        raise InvalidAction(f"{target.name} est déjà mort.")
    if target.pk == actor.pk:
        raise InvalidAction("Vous ne pouvez pas vous désigner vous-même.")
    return target


def submit_message(game, player, text, channel=Channel.PUBLIC):
    """Publie un message dans le canal public (le jour) ou celui des loups (la nuit)."""
    text = (text or "").strip()
    if not text:
        raise InvalidAction("Le message est vide.")
    if len(text) > MESSAGE_MAX_LENGTH:
        raise InvalidAction(f"Le message dépasse {MESSAGE_MAX_LENGTH} caractères.")
    with transaction.atomic():
        game, player = _load(game, player)
        if channel == Channel.WOLVES:
            if player.role != Role.WEREWOLF:
                raise InvalidAction("Le canal des loups est réservé aux loups.")
            _require_phase(game, Phase.NIGHT_WOLVES)
        elif channel == Channel.PUBLIC:
            if game.phase not in DAY_PHASES:
                raise InvalidAction("Le village dort : la place publique est fermée la nuit.")
        else:
            raise InvalidAction("Canal inconnu.")
        return Message.objects.create(
            game=game,
            author=player,
            kind=MessageKind.CHAT,
            channel=channel,
            content=text,
            day_number=game.day_number,
            phase=game.phase,
        )


def submit_vote(game, voter, target=None):
    """Vote de jour ; ``target=None`` = vote blanc."""
    with transaction.atomic():
        game, voter = _load(game, voter)
        _require_phase(game, Phase.DAY_VOTE)
        if Vote.objects.filter(game=game, day_number=game.day_number, voter=voter).exists():
            raise InvalidAction("Vous avez déjà voté aujourd'hui.")
        # Le jour, un loup peut voter contre un loup (bluff).
        target = None if target is None else _target(game, target, actor=voter)
        vote = Vote.objects.create(
            game=game, day_number=game.day_number, voter=voter, target=target
        )
    try_advance(game)
    return vote


def submit_seer_inspection(game, seer, target):
    """La voyante sonde un joueur ; le rôle révélé est renvoyé dans l'action."""
    with transaction.atomic():
        game, seer = _load(game, seer)
        _require_phase(game, Phase.NIGHT_SEER)
        if seer.role != Role.SEER:
            raise InvalidAction("Seule la voyante peut sonder un joueur.")
        if NightAction.objects.filter(
            game=game, night_number=game.day_number, actor=seer,
            action_type=NightActionType.SEER_INSPECT,
        ).exists():
            raise InvalidAction("Vous avez déjà sondé un joueur cette nuit.")
        target = _target(game, target, actor=seer)
        action = NightAction.objects.create(
            game=game,
            night_number=game.day_number,
            actor=seer,
            action_type=NightActionType.SEER_INSPECT,
            target=target,
            revealed_role=target.role,
        )
    try_advance(game)
    return action


def submit_wolf_target(game, wolf, target):
    """Un loup désigne sa victime.

    Un loup peut changer d'avis tant que la phase est ouverte. Quand un loup
    humain choisit, ses compères IA s'alignent sur lui : l'humain a le dernier
    mot (plan B du sprint), ce qui évite un « désaccord » involontaire.
    """
    with transaction.atomic():
        game, wolf = _load(game, wolf)
        _require_phase(game, Phase.NIGHT_WOLVES)
        if wolf.role != Role.WEREWOLF:
            raise InvalidAction("Seuls les loups choisissent une victime.")
        target = _target(game, target, actor=wolf)
        if target.role == Role.WEREWOLF:
            raise InvalidAction("Un loup ne peut pas dévorer un autre loup.")
        actors = [wolf]
        if wolf.is_human:
            actors += list(
                game.players.filter(role=Role.WEREWOLF, is_alive=True, is_human=False)
            )
        for actor in actors:
            NightAction.objects.update_or_create(
                game=game,
                night_number=game.day_number,
                actor=actor,
                action_type=NightActionType.WOLF_TARGET,
                defaults={"target": target},
            )
        action = NightAction.objects.get(
            game=game, night_number=game.day_number, actor=wolf,
            action_type=NightActionType.WOLF_TARGET,
        )
    try_advance(game)
    return action


def submit_witch_decision(game, witch, heal=False, kill_target=None):
    """Décision complète de la sorcière, en une fois : soin et/ou poison, ou rien.

    - Le soin ne peut viser que la victime des loups (elle-même comprise).
    - Chaque potion n'est utilisable qu'une fois par partie.
    - Elle ne peut pas soigner et empoisonner la même personne.
    """
    with transaction.atomic():
        game, witch = _load(game, witch)
        _require_phase(game, Phase.NIGHT_WITCH)
        if witch.role != Role.WITCH:
            raise InvalidAction("Seule la sorcière utilise les potions.")
        if NightAction.objects.filter(
            game=game, night_number=game.day_number, actor=witch,
            action_type__in=[
                NightActionType.WITCH_HEAL,
                NightActionType.WITCH_KILL,
                NightActionType.WITCH_PASS,
            ],
        ).exists():
            raise InvalidAction("Vous avez déjà pris votre décision cette nuit.")

        rows = []
        victim = wolf_victim(game)
        if heal:
            if not witch.has_life_potion:
                raise InvalidAction("Votre potion de vie a déjà été utilisée.")
            if victim is None:
                raise InvalidAction("Personne n'a été désigné par les loups cette nuit.")
            rows.append((NightActionType.WITCH_HEAL, victim))
        if kill_target is not None:
            if not witch.has_death_potion:
                raise InvalidAction("Votre potion de mort a déjà été utilisée.")
            target = _target(game, kill_target, actor=witch)
            if heal and victim and target.pk == victim.pk:
                raise InvalidAction("Vous ne pouvez pas soigner et empoisonner la même personne.")
            rows.append((NightActionType.WITCH_KILL, target))
        if not rows:
            rows.append((NightActionType.WITCH_PASS, None))

        actions = [
            NightAction.objects.create(
                game=game,
                night_number=game.day_number,
                actor=witch,
                action_type=action_type,
                target=target,
            )
            for action_type, target in rows
        ]
    try_advance(game)
    return actions
