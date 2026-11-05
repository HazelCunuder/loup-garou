"""Données d'affichage du plateau, construites à partir de la vue autorisée.

Le template ne reçoit que ce que ``player_view`` autorise : aucune donnée
secrète d'un autre joueur ne peut atterrir dans le HTML ou dans un json_script.
"""

from game.models import Channel, MessageKind, Phase, Role, Winner

# Avatars neutres attribués par siège : ils ne trahissent ni rôle ni personnalité.
SEAT_AVATARS = ["🧑‍🌾", "👩‍🌾", "🧔", "👵", "👨‍🦰", "👩‍🦱", "🧓", "👨‍🦳", "👩‍🦳", "🧑‍🦱", "👱", "👴"]

ROLE_PROFILES = {
    Role.WEREWOLF: {
        "key": "loup",
        "avatar": "🐺",
        "description": (
            "Vous chassez en meute : votre allié partage votre table de chasse. "
            "Chaque nuit, un canal secret s'ouvre entre vous pour délibérer puis "
            "désigner la proie du village."
        ),
    },
    Role.SEER: {
        "key": "voyante",
        "avatar": "🔮",
        "description": (
            "Chaque nuit, vous ouvrez l'œil : désignez un habitant et percez "
            "immédiatement son rôle secret."
        ),
    },
    Role.WITCH: {
        "key": "sorciere",
        "avatar": "🧙‍♀️",
        "description": (
            "Vous veillez sur le village avec deux fioles : une potion de vie pour "
            "sauver la victime des loups, et une potion de mort pour éliminer un suspect."
        ),
    },
    Role.VILLAGER: {
        "key": "villageois",
        "avatar": "🌾",
        "description": (
            "Le cœur du village, sans pouvoir particulier. La nuit, vos seuls alliés "
            "sont le sommeil et votre instinct : au réveil, il faudra voter."
        ),
    },
}

# Clés de ``?role=`` (mode DEBUG) vers les rôles du moteur.
ROLE_BY_KEY = {profile["key"]: role for role, profile in ROLE_PROFILES.items()}

NIGHT_PHASES = (Phase.NIGHT_SEER, Phase.NIGHT_WOLVES, Phase.NIGHT_WITCH)

# Libellés courts de la bannière (« Jour 2 · Débat », « Nuit 2 · Les loups »).
PHASE_SHORT_LABELS = {
    Phase.NIGHT_SEER: "La voyante",
    Phase.NIGHT_WOLVES: "Les loups",
    Phase.NIGHT_WITCH: "La sorcière",
    Phase.DAWN: "Aube",
    Phase.DAY_DEBATE: "Débat",
    Phase.DAY_VOTE: "Le vote",
    Phase.VOTE_RESULT: "Verdict",
}

PHASE_DISPLAY = {
    Phase.NIGHT_SEER: ("🔮", "La voyante sonde les âmes du village."),
    Phase.NIGHT_WOLVES: ("🐺", "Les loups choisissent leur proie."),
    Phase.NIGHT_WITCH: ("🧪", "La sorcière se penche sur ses fioles."),
    Phase.DAWN: ("🌅", "Le village découvre ce que la nuit a emporté."),
    Phase.DAY_DEBATE: ("☀️", "Chacun partage ses soupçons."),
    Phase.DAY_VOTE: ("⚖️", "Désignez un suspect, ou votez blanc."),
    Phase.VOTE_RESULT: ("🔥", "Le village découvre le verdict."),
    Phase.GAME_OVER: ("🏁", "La partie est terminée."),
}

COMPOSITION = [
    {"name": "Loups-Garous", "icon": "🐺", "count": 2, "note": "Les prédateurs du village."},
    {"name": "Voyante", "icon": "🔮", "count": 1, "note": "Découvre le rôle d’un habitant chaque nuit."},
    {"name": "Sorcière", "icon": "🧪", "count": 1, "note": "Dispose d’une potion de vie et d’une potion de mort."},
    {"name": "Villageois", "icon": "🌾", "count": 3, "note": "Le cœur du village, sans pouvoir particulier."},
]

PHASES_REMINDER = [
    {"name": "La Nuit", "icon": "🌙", "desc": "La voyante scrute, les loups choisissent leur proie, la sorcière agit."},
    {"name": "Le Jour", "icon": "☀️", "desc": "Le village se réveille et découvre ce que la nuit a emporté."},
    {"name": "Le Vote", "icon": "⚖️", "desc": "Les habitants désignent un suspect à envoyer au bûcher."},
]


def avatar_for(player):
    if player["is_me"] and player["role"]:
        return ROLE_PROFILES[player["role"]]["avatar"]
    return SEAT_AVATARS[player["seat"] % len(SEAT_AVATARS)]


def status_phase(view):
    game = view["game"]
    phase = game["phase"]
    icon, desc = PHASE_DISPLAY[phase]
    if phase == Phase.GAME_OVER:
        key = "jour"
        label = "Victoire du village" if game["winner"] == Winner.VILLAGE else "Victoire des loups-garous"
    else:
        key = "nuit" if phase in NIGHT_PHASES else "vote" if phase == Phase.DAY_VOTE else "jour"
        moment = "Nuit" if phase in NIGHT_PHASES else "Jour"
        label = f"{moment} {game['day']} · {PHASE_SHORT_LABELS[phase]}"
    return {"key": key, "icon": icon, "label": label, "desc": desc}


def board_context(view):
    """Contexte du template ``game/village.html`` pour le joueur de ``view``."""
    me = view["me"]
    players = view["players"]
    avatars = {p["id"]: avatar_for(p) for p in players}
    names = {p["id"]: p["name"] for p in players}
    profile = ROLE_PROFILES[me["role"]]

    seats = [
        {
            "id": p["id"],
            "name": p["name"],
            "is_human": p["is_me"],
            "avatar": avatars[p["id"]],
            "role": p["role_label"] if p["is_me"] else "Inconnu",
            "is_alive": p["is_alive"],
        }
        for p in players
    ]
    public = [m for m in view["messages"] if m["channel"] == Channel.PUBLIC]
    announcements = [m["content"] for m in reversed(public) if m["kind"] == MessageKind.ANNOUNCEMENT]
    partners = view["private"].get("wolf_partners") or []

    return {
        "board": {
            "village": "Thiercelieux",
            "edition": "Édition Classique",
            "player_count": len(players),
            "status": f"Jour {view['game']['day']} · {view['game']['phase_label']}",
        },
        "players": seats,
        "composition": COMPOSITION,
        "phases": PHASES_REMINDER,
        "discussion": [
            {"name": names[m["author_id"]], "avatar": avatars[m["author_id"]], "text": m["content"]}
            for m in public
            if m["kind"] == MessageKind.CHAT
        ],
        "status_phase": status_phase(view),
        "announcements": announcements,
        "human": {
            "name": me["name"],
            "avatar": profile["avatar"],
            "role": me["role_label"],
            "role_description": profile["description"],
            "is_alive": me["is_alive"],
        },
        "night": {
            "role_key": profile["key"],
            "role_name": me["role_label"],
            "players": [
                {"id": p["id"], "name": p["name"], "avatar": avatars[p["id"]]}
                for p in players
                if not p["is_me"] and p["is_alive"]
            ],
            # Uniquement les rôles que le joueur connaît (morts, compère, sondages).
            "ai_roles": {
                p["name"]: p["role_label"] for p in players if p["role"] and not p["is_me"]
            },
            "wolf_ally": (
                {"id": partners[0]["id"], "name": partners[0]["name"], "avatar": avatars[partners[0]["id"]]}
                if partners
                else None
            ),
        },
    }
