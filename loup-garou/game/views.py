from django.shortcuts import render


def village_view(request):
    """
    Plateau de jeu du Loup-Garou de Thiercelieux — édition classique.

    Cette vue ne simule aucune partie : elle expose uniquement la disposition
    initiale du village (7 places, rôles secrets, composition et rappel des phases).
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

    context = {
        'board': board,
        'players': players,
        'composition': composition,
        'phases': phases,
        'human': players[0],
    }
    return render(request, 'game/village.html', context)
