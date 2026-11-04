from django.shortcuts import render


# Profils du joueur humain pour les interfaces nocturnes dédiées (démo).
# Le rôle n'est pas encore distribué par un backend : le paramètre `?role=`
# permet de prévisualiser chacune des quatre interfaces nocturne dédiées.
NIGHT_ROLES = {
    'loup': {
        'name': 'Loup-Garou',
        'avatar': '🐺',
        'description': (
            "Vous chassez en meute : votre allié IA partage votre table de chasse. "
            "Chaque nuit, un canal secret s'ouvre entre vous deux pour délibérer "
            "puis désigner la proie du village."
        ),
        # Démo : rôles secrets des IA, cohérents avec la composition (2 loups
        # = le joueur humain + son allié Léa).
        'ai_roles': {
            'Victor': 'Voyante',
            'Chloé': 'Sorcière',
            'Lucas': 'Villageois',
            'Thomas': 'Villageois',
            'Marc': 'Villageois',
        },
        'wolf_ally': {'id': 5, 'name': 'Léa', 'avatar': '👁️'},
    },
    'voyante': {
        'name': 'Voyante',
        'avatar': '🔮',
        'description': (
            "Chaque nuit, vous ouvrez l'œil : une modale vous permet de désigner "
            "un habitant et de percer immédiatement son rôle secret."
        ),
        'ai_roles': {
            'Victor': 'Loup-Garou',
            'Chloé': 'Sorcière',
            'Lucas': 'Villageois',
            'Léa': 'Villageois',
            'Thomas': 'Villageois',
            'Marc': 'Loup-Garou',
        },
    },
    'sorciere': {
        'name': 'Sorcière',
        'avatar': '🧙‍♀️',
        'description': (
            "Vous veillez sur le village avec deux fioles : une potion de vie "
            "pour sauver une victime des loups, et une potion de mort pour "
            "éliminer un suspect."
        ),
        'ai_roles': {
            'Victor': 'Loup-Garou',
            'Chloé': 'Villageois',
            'Lucas': 'Voyante',
            'Léa': 'Villageois',
            'Thomas': 'Villageois',
            'Marc': 'Loup-Garou',
        },
    },
    'villageois': {
        'name': 'Villageois',
        'avatar': '🌾',
        'description': (
            "Le cœur du village, sans pouvoir particulier. Cette nuit, vos seuls "
            "alliés sont le sommeil et votre instinct : au réveil, il faudra voter."
        ),
        'ai_roles': {
            'Victor': 'Loup-Garou',
            'Chloé': 'Sorcière',
            'Lucas': 'Voyante',
            'Léa': 'Villageois',
            'Thomas': 'Villageois',
            'Marc': 'Loup-Garou',
        },
    },
}


def village_view(request):
    """
    Plateau de jeu du Loup-Garou de Thiercelieux — édition classique.

    Cette vue ne simule aucune partie : elle expose uniquement la disposition
    initiale du village (7 places, rôles secrets, composition et rappel des phases).
    Le paramètre `?role=` (démo) sélectionne le rôle du joueur humain pour afficher
    l'interface nocturne dédiée correspondante.
    """
    board = {
        'village': 'Thiercelieux',
        'edition': 'Édition Classique',
        'player_count': 7,
        'status': 'Plateau préparé',
    }

    # 7 places : 1 joueur humain + 6 personnalités IA.
    # Tous les habitants sont vivants : nous présentons le plateau, pas une partie en cours.
    players = [
        {
            'id': 1,
            'name': 'Alexandre',
            'is_human': True,
            'role': 'Sorcière',
            'role_description': (
                "Vous veillez sur le village avec deux fioles : une potion de vie "
                "pour sauver une victime des loups, et une potion de mort pour "
                "éliminer un suspect."
            ),
            'persona': 'Votre place',
            'persona_desc': 'Joueur humain — votre rôle reste secret.',
            'avatar': '🧙‍♀️',
        },
        {
            'id': 2,
            'name': 'Victor',
            'is_human': False,
            'role': 'Inconnu',
            'role_description': 'Rôle secret protégé par le Fog of War.',
            'persona': 'Le Stratège',
            'persona_desc': 'Cartésien, traque les contradictions logiques.',
            'avatar': '🧠',
        },
        {
            'id': 3,
            'name': 'Chloé',
            'is_human': False,
            'role': 'Inconnu',
            'role_description': 'Rôle secret protégé par le Fog of War.',
            'persona': 'La Mauvaise Joueuse',
            'persona_desc': 'Susceptible, contre-attaque vivement.',
            'avatar': '⚡',
        },
        {
            'id': 4,
            'name': 'Lucas',
            'is_human': False,
            'role': 'Inconnu',
            'role_description': 'Rôle secret protégé par le Fog of War.',
            'persona': 'Le Cynique',
            'persona_desc': 'Ironique, détaché, amateur d’humour noir.',
            'avatar': '🎭',
        },
        {
            'id': 5,
            'name': 'Léa',
            'is_human': False,
            'role': 'Inconnu',
            'role_description': 'Rôle secret protégé par le Fog of War.',
            'persona': 'La Paranoïaque',
            'persona_desc': 'Anxieuse, suspecte les joueurs silencieux.',
            'avatar': '👁️',
        },
        {
            'id': 6,
            'name': 'Thomas',
            'is_human': False,
            'role': 'Inconnu',
            'role_description': 'Rôle secret protégé par le Fog of War.',
            'persona': 'La Diplomate',
            'persona_desc': 'Calme, recherche le consensus du village.',
            'avatar': '🕊️',
        },
        {
            'id': 7,
            'name': 'Marc',
            'is_human': False,
            'role': 'Inconnu',
            'role_description': 'Rôle secret protégé par le Fog of War.',
            'persona': 'L’Impulsif',
            'persona_desc': 'Réagit à chaud et vote à l’instinct.',
            'avatar': '🔥',
        },
    ]

    # --- Rôle du joueur humain (démo) : contrôlé par le paramètre `?role=` ---
    role_key = request.GET.get('role') or 'sorciere'
    if role_key not in NIGHT_ROLES:
        role_key = 'sorciere'
    role_profile = NIGHT_ROLES[role_key]
    human = players[0]
    human['role'] = role_profile['name']
    human['role_description'] = role_profile['description']
    human['avatar'] = role_profile['avatar']

    # Données nocturnes transmises aux interfaces dédiées (démo : côté client).
    night = {
        'role_key': role_key,
        'role_name': role_profile['name'],
        # Cibles possibles : les six habitants IA.
        'players': [
            {
                'id': player['id'],
                'name': player['name'],
                'avatar': player['avatar'],
                'persona': player['persona'],
            }
            for player in players[1:]
        ],
        # Démo : rôles secrets des IA, consommés par la voyante (Fog of War).
        'ai_roles': role_profile['ai_roles'],
        # Démo : unique à l'interface du Loup-Garou (allé chantant IA).
        'wolf_ally': role_profile.get('wolf_ally'),
    }

    # Composition classique du village (MVP 7 joueurs).
    composition = [
        {
            'name': 'Loups-Garous',
            'icon': '🐺',
            'count': 2,
            'note': 'Les prédateurs du village.',
        },
        {
            'name': 'Voyante',
            'icon': '🔮',
            'count': 1,
            'note': 'Découvre le rôle d’un habitant chaque nuit.',
        },
        {
            'name': 'Sorcière',
            'icon': '🧪',
            'count': 1,
            'note': 'Dispose d’une potion de vie et d’une potion de mort.',
        },
        {
            'name': 'Villageois',
            'icon': '🌾',
            'count': 3,
            'note': 'Le cœur du village, sans pouvoir particulier.',
        },
    ]

    # Rappel statique du déroulement, sans interaction.
    phases = [
        {
            'name': 'La Nuit',
            'icon': '🌙',
            'desc': 'Les loups choisissent leur proie, la voyante scrute, la sorcière agit.',
        },
        {
            'name': 'Le Jour',
            'icon': '☀️',
            'desc': 'Le village se réveille et découvre ce que la nuit a emporté.',
        },
        {
            'name': 'Le Vote',
            'icon': '⚖️',
            'desc': 'Les habitants désignent un suspect à envoyer au bûcher.',
        },
    ]

    # Extraits publics de la dernière veillée, affichés sur la place du village.
    # Démo statique : la discussion n'est pas encore reliée à un modèle Django.
    discussion = [
        {
            'name': 'Thomas',
            'avatar': '🕊️',
            'persona': 'La Diplomate',
            'text': 'Le village est réuni. Avant que la nuit ne tombe, disons chacun ce que nous avons vu.',
        },
        {
            'name': 'Victor',
            'avatar': '🧠',
            'persona': 'Le Stratège',
            'text': "Aucune contradiction dans les déclarations d'hier. Les loups se protègent en restant vagues.",
        },
        {
            'name': 'Léa',
            'avatar': '👁️',
            'persona': 'La Paranoïaque',
            'text': 'Et Marc, qui n’a presque rien dit ? Les silences me pèsent plus que les mots...',
        },
        {
            'name': 'Marc',
            'avatar': '🔥',
            'persona': 'L’Impulsif',
            'text': 'Parce que réfléchir avant de parler, c’est suspect maintenant ? Votez, on verra bien !',
        },
        {
            'name': 'Lucas',
            'avatar': '🎭',
            'persona': 'Le Cynique',
            'text': 'Magnifique stratégie : le bûcher au hasard. Nos aïeux seraient fiers de nous.',
        },
        {
            'name': 'Chloé',
            'avatar': '⚡',
            'persona': 'La Mauvaise Joueuse',
            'text': 'Très bien, puisque tout le monde accuse sans preuve, je commencerai par me défendre.',
        },
        {
            'name': 'Thomas',
            'avatar': '🕊️',
            'persona': 'La Diplomate',
            'text': 'Gardons nos têtes froides : la nuit sera assez cruelle pour le village.',
        },
    ]

    # État courant du village, affiché par la bannière temps réel.
    # Démo statique : la phase de départ est fournie ici, la simulation
    # (rotation Jour → Vote → Nuit) tourne ensuite côté client.
    status_phase = {
        'key': 'jour',
        'icon': '☀️',
        'label': 'Jour 1 · Le village se réveille',
        'desc': 'Chacun découvre ce que la nuit a emporté.',
    }

    # Annonces du Maître du jeu, défilées en continu dans la bannière.
    announcements = [
        'Réunion de la place : que chacun se présente sans mentir… ou presque.',
        'Les rôles ont été distribués. Deux loups rôdent parmi nous.',
        'Personne n’est mort cette nuit. Thiercelieux respire… pour l’instant.',
        'Le vote approche : un suspect finira sur le bûcher.',
        'Le silence des loups me plaît peu. Réfléchissez avant de parler.',
    ]

    context = {
        'board': board,
        'players': players,
        'composition': composition,
        'phases': phases,
        'discussion': discussion,
        'status_phase': status_phase,
        'announcements': announcements,
        'human': human,
        'night': night,
    }
    return render(request, 'game/village.html', context)
