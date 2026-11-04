from django.shortcuts import render

def village_view(request):
    """
    Vue principale du village Loup-Garou :
    - Plateau 7 Joueurs (1 humain + 6 IA avec leurs personnalités)
    - Bannière d'état en temps réel (Jour / Nuit / Vote / Annonces du MJ)
    - Zone centrale de discussion publique (Chat du village)
    - Thème et palette violette / nocturne immersive
    """
    game_state = {
        'id': 'LG-7029',
        'phase': 'JOUR',          # 'JOUR', 'NUIT', 'VOTE'
        'tour': 1,
        'timer_seconds': 42,
        'max_timer': 45,
        'alive_count': 6,
        'dead_count': 1,
        'total_players': 7,
        'mj_announcement': (
            "Le village s'éveille dans l'angoisse. Au lever du jour, les habitants ont découvert "
            "le corps mutilé de Marc l'Impulsif près de la fontaine... Les Loups-Garous rodent parmi nous. "
            "Le débat public est ouvert : démasquez les coupables avant le vote !"
        ),
    }

    # Données des 7 joueurs selon le cadrage v2.1 (MVP 7 joueurs : 2 Loups, 1 Voyante, 1 Sorcière, 3 Villageois)
    players = [
        {
            'id': 1,
            'name': 'Alexandre (Vous)',
            'is_human': True,
            'is_alive': True,
            'role': 'Sorcière',
            'role_revealed': True,      # L'humain connaît toujours son rôle
            'role_description': 'Vous disposez d\'une potion de vie (auto-sauvetage permis si ciblée) et d\'une potion de mort.',
            'persona': 'Joueur Humain',
            'avatar': '🧙‍♀️',
            'avatar_bg': 'from-purple-600 to-indigo-800',
            'has_life_potion': True,
            'has_death_potion': True,
            'votes_received': 0,
            'badge': 'Vous',
        },
        {
            'id': 2,
            'name': 'Victor',
            'is_human': False,
            'is_alive': True,
            'role': 'Inconnu',
            'role_revealed': False,
            'role_description': 'Rôle secret protégé par le Fog of War',
            'persona': 'Le Stratège',
            'persona_desc': 'Cartésien, traque les contradictions logiques et les anomalies de vote.',
            'avatar': '🧠',
            'avatar_bg': 'from-blue-600 to-indigo-900',
            'votes_received': 1,
            'badge': 'Le Stratège',
        },
        {
            'id': 3,
            'name': 'Chloé',
            'is_human': False,
            'is_alive': True,
            'role': 'Inconnu',
            'role_revealed': False,
            'role_description': 'Rôle secret protégé par le Fog of War',
            'persona': 'La Mauvaise Joueuse',
            'persona_desc': 'Susceptible, contre-attaque violemment dès qu\'on la suspecte.',
            'avatar': '⚡',
            'avatar_bg': 'from-rose-600 to-pink-900',
            'votes_received': 2,
            'badge': 'La Mauvaise Joueuse',
        },
        {
            'id': 4,
            'name': 'Lucas',
            'is_human': False,
            'is_alive': True,
            'role': 'Inconnu',
            'role_revealed': False,
            'role_description': 'Rôle secret protégé par le Fog of War',
            'persona': 'Le Cynique',
            'persona_desc': 'Ironique, détend l\'atmosphère avec humour noir et détachement.',
            'avatar': '🎭',
            'avatar_bg': 'from-amber-600 to-purple-900',
            'votes_received': 0,
            'badge': 'Le Cynique',
        },
        {
            'id': 5,
            'name': 'Léa',
            'is_human': False,
            'is_alive': True,
            'role': 'Inconnu',
            'role_revealed': False,
            'role_description': 'Rôle secret protégé par le Fog of War',
            'persona': 'La Paranoïaque',
            'persona_desc': 'Anxieuse, accuse rapidement les joueurs silencieux ou trop calmes.',
            'avatar': '👁️',
            'avatar_bg': 'from-violet-600 to-fuchsia-900',
            'votes_received': 0,
            'badge': 'La Paranoïaque',
        },
        {
            'id': 6,
            'name': 'Thomas',
            'is_human': False,
            'is_alive': True,
            'role': 'Inconnu',
            'role_revealed': False,
            'role_description': 'Rôle secret protégé par le Fog of War',
            'persona': 'La Diplomate',
            'persona_desc': 'Calme, recherche le consensus et cherche à éviter les lynchages hâtifs.',
            'avatar': '🕊️',
            'avatar_bg': 'from-teal-600 to-cyan-900',
            'votes_received': 0,
            'badge': 'La Diplomate',
        },
        {
            'id': 7,
            'name': 'Marc',
            'is_human': False,
            'is_alive': False,        # Éliminé la nuit 1
            'role': 'Villageois',
            'role_revealed': True,    # Conformément au cadrage : rôle révélé à sa mort !
            'role_description': 'Simple habitant du village, assassiné lors de la Nuit 1.',
            'persona': 'L\'Impulsif',
            'persona_desc': 'Réagissait à chaud, votait à l\'instinct selon le dernier argument entendu.',
            'avatar': '🔥',
            'avatar_bg': 'from-gray-700 to-zinc-900',
            'death_reason': 'Dévoré par les Loups (Nuit 1)',
            'votes_received': 0,
            'badge': 'L\'Impulsif (Mort)',
        },
    ]

    # Historique de discussion initiale
    chat_messages = [
        {
            'type': 'MJ',
            'author': 'Maître du Jeu',
            'time': '08:00',
            'content': (
                "🌕 La nuit s'achève... Le village s'éveille. Un hurlement retentit près de la fontaine : "
                "Marc l'Impulsif a été dévoré par les Loups ! Son rôle était : 🧑‍🌾 Simple Villageois."
            ),
        },
        {
            'type': 'AI',
            'player_id': 4,
            'author': 'Lucas (Le Cynique)',
            'avatar': '🎭',
            'time': '08:01',
            'content': "Une première nuit classique. Marc parlait trop fort hier soir... Les loups ont au moins le bon goût d'éliminer les plus bruyants en premier.",
        },
        {
            'type': 'AI',
            'player_id': 5,
            'author': 'Léa (La Paranoïaque)',
            'avatar': '👁️',
            'time': '08:02',
            'content': "Vous trouvez ça drôle Lucas ? Pourquoi regarder la fontaine alors que Victor n'a pas décroché un seul mot depuis l'aube ? Être aussi calme quand un villageois meurt, c'est louche !",
        },
        {
            'type': 'AI',
            'player_id': 2,
            'author': 'Victor (Le Stratège)',
            'avatar': '🧠',
            'time': '08:03',
            'content': "Inutile de paniquer, Léa. Analysons les faits : les loups ont attaqué un profil impulsif pour semer la confusion. Observer avant d'accuser au hasard évite précisément de faire le jeu des loups.",
        },
        {
            'type': 'AI',
            'player_id': 3,
            'author': 'Chloé (La Mauvaise Joueuse)',
            'avatar': '⚡',
            'time': '08:04',
            'content': "Si quelqu'un ose voter contre moi aujourd'hui sous prétexte que je me défends, je vous promets qu'on va perdre la partie ! Regardez plutôt du côté de Thomas ou d'Alexandre !",
        },
        {
            'type': 'AI',
            'player_id': 6,
            'author': 'Thomas (La Diplomate)',
            'avatar': '🕊️',
            'time': '08:04',
            'content': "Gardons la tête froide. Alexandre, tu es resté silencieux. Quel est ton ressenti sur les soupçons de Léa et l'attitude de Chloé ?",
        },
    ]

    context = {
        'game_state': game_state,
        'players': players,
        'chat_messages': chat_messages,
    }
    return render(request, 'game/village.html', context)
