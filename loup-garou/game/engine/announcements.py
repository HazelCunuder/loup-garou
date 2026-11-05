"""Annonces du Maître du Jeu, publiées dans le canal public."""

from game.models import Channel, Message, MessageKind, Phase, Role, Winner

NIGHT_PHASES = (Phase.NIGHT_SEER, Phase.NIGHT_WOLVES, Phase.NIGHT_WITCH)

ROLE_WITH_ARTICLE = {
    Role.WEREWOLF: "un Loup-Garou",
    Role.VILLAGER: "un Villageois",
    Role.SEER: "la Voyante",
    Role.WITCH: "la Sorcière",
}


def announce(game, text, *, phase, day_number):
    return Message.objects.create(
        game=game,
        author=None,
        kind=MessageKind.ANNOUNCEMENT,
        channel=Channel.PUBLIC,
        content=text,
        phase=phase,
        day_number=day_number,
    )


def game_start_text():
    return (
        "Nuit 1. Les rôles ont été distribués : deux loups-garous se cachent "
        "parmi vous. Le village s'endort…"
    )


def death_text(player):
    return f"{player.name} était {ROLE_WITH_ARTICLE[player.role]}."


def on_enter(game, previous_phase, phase, day_number, winner=None):
    """Annonce l'entrée dans ``phase`` (appelée dans la transaction de ``advance``).

    L'aube et le résultat du vote sont annoncés par la résolution elle-même,
    qui connaît les morts.
    """
    if phase == Phase.GAME_OVER:
        text = (
            "Victoire du village ! Tous les loups-garous ont été démasqués."
            if winner == Winner.VILLAGE
            else "Victoire des loups-garous ! Ils sont désormais aussi nombreux que les villageois."
        )
    elif phase in NIGHT_PHASES and previous_phase not in NIGHT_PHASES:
        text = f"Nuit {day_number}. Le village s'endort…"
    elif phase == Phase.DAY_DEBATE:
        text = "Le débat est ouvert : partagez vos soupçons."
    elif phase == Phase.DAY_VOTE:
        text = "Place au vote : désignez un suspect, ou votez blanc."
    else:
        return None
    return announce(game, text, phase=phase, day_number=day_number)
