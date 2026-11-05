"""Résolution de la nuit (à l'aube) et du vote (en entrant dans VOTE_RESULT).

Appelées par la state machine dans la transaction de ``advance`` : toute
écriture est annulée si la transition échoue.
"""

from collections import Counter

from game.models import DeathCause, Phase, Player, Role
from night_time.models import NightAction, NightActionType
from voting.models import Vote

from .announcements import announce, death_text


def wolf_victim(game, night_number=None):
    """Cible commune des loups pour la nuit, ou None.

    Seuls les loups vivants qui ont agi comptent : un loup seul décide seul ;
    deux loups qui visent des joueurs différents ne tuent personne.
    """
    night_number = night_number or game.day_number
    targets = set(
        NightAction.objects.filter(
            game=game,
            night_number=night_number,
            action_type=NightActionType.WOLF_TARGET,
            actor__is_alive=True,
            actor__role=Role.WEREWOLF,
        ).values_list("target_id", flat=True)
    )
    if len(targets) != 1:
        return None
    return Player.objects.get(pk=targets.pop())


def _kill(player, day_number, cause):
    player.is_alive = False
    player.died_on_day = day_number
    player.death_cause = cause
    player.save(update_fields=["is_alive", "died_on_day", "death_cause"])


def resolve_night(game):
    """Applique les actions de la nuit ``game.day_number`` et renvoie les morts."""
    night = game.day_number
    victim = wolf_victim(game, night)
    witch_actions = {
        a.action_type: a
        for a in NightAction.objects.filter(
            game=game,
            night_number=night,
            actor__role=Role.WITCH,
            actor__is_alive=True,
            action_type__in=[NightActionType.WITCH_HEAL, NightActionType.WITCH_KILL],
        ).select_related("actor", "target")
    }

    deaths = []
    heal = witch_actions.get(NightActionType.WITCH_HEAL)
    if heal and heal.actor.has_life_potion:
        heal.actor.has_life_potion = False
        heal.actor.save(update_fields=["has_life_potion"])
        if victim and heal.target_id == victim.pk:
            victim = None
    if victim:
        deaths.append((victim, DeathCause.WOLVES))

    kill = witch_actions.get(NightActionType.WITCH_KILL)
    if kill:
        witch = Player.objects.get(pk=kill.actor_id)  # potions à jour après le soin
        if witch.has_death_potion:
            witch.has_death_potion = False
            witch.save(update_fields=["has_death_potion"])
            if all(kill.target_id != dead.pk for dead, _ in deaths):
                deaths.append((kill.target, DeathCause.WITCH))

    for player, cause in deaths:
        _kill(player, night, cause)

    if deaths:
        details = " ".join(death_text(p) for p, _ in deaths)
        names = " et ".join(p.name for p, _ in deaths)
        verb = "a été retrouvé mort" if len(deaths) == 1 else "ont été retrouvés morts"
        text = f"Le jour se lève. {names} {verb} cette nuit. {details}"
    else:
        text = "Le jour se lève. Personne n'est mort cette nuit."
    announce(game, text, phase=Phase.DAWN, day_number=night)
    return [p for p, _ in deaths]


def resolve_vote(game):
    """Applique le vote du jour ``game.day_number`` et renvoie l'éliminé éventuel.

    Les votes blancs ne comptent pas. Le joueur le plus désigné est éliminé ;
    une égalité en tête ou l'absence de vote exprimé n'élimine personne.
    """
    day = game.day_number
    counts = Counter(
        Vote.objects.filter(game=game, day_number=day, target__isnull=False).values_list(
            "target_id", flat=True
        )
    )
    eliminated = None
    if not counts:
        text = "Personne n'a été désigné : le village s'endort sans lynchage."
    else:
        ranking = counts.most_common()
        top = ranking[0][1]
        leaders = [pk for pk, n in ranking if n == top]
        if len(leaders) > 1:
            names = " et ".join(
                Player.objects.filter(pk__in=leaders).order_by("seat").values_list("name", flat=True)
            )
            text = (
                f"Égalité entre {names} avec {top} voix chacun : présomption "
                "d'innocence, personne n'est éliminé."
            )
        else:
            eliminated = Player.objects.get(pk=leaders[0])
            _kill(eliminated, day, DeathCause.VOTE)
            text = (
                f"Le village a tranché : {eliminated.name} est éliminé avec {top} voix. "
                f"{death_text(eliminated)}"
            )
    announce(game, text, phase=Phase.VOTE_RESULT, day_number=day)
    return eliminated
