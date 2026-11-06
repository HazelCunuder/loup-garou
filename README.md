# 🐺 Le Loup-Garou de Thiercelieux

Jeu du Loup-Garou en solo dans le navigateur : **un joueur humain** affronte
**six agents IA** (Mistral), chacun avec sa propre personnalité, dans un village
de 7 habitants. Le tout dans un style médiéval classique (parchemin, bois, or et
cire à sceller), avec les places du village disposées en cercle autour de
l'emblème de **Thiercelieux**.

> La partie est **jouable de bout en bout** : distribution des rôles, nuits,
> débats, votes et conditions de victoire sont gérés par un moteur côté serveur.
> Le front interroge l'API toutes les 1,5 s pour afficher l'état en direct.

## 📁 Structure du projet

```
loup-garou/
├── .env.example            # Modèle du fichier .env (clé API Mistral)
├── requirements.txt        # Dépendances Python
├── Docs/                   # Cadrage du projet (PDF)
├── loup-garou/             # Projet Django
│   ├── loupgarou/          # Configuration (settings, urls)
│   ├── game/               # App principale
│   │   ├── models.py       #   Game, Player, Message
│   │   ├── engine/         #   Moteur de jeu (règles, tours, state machine, Fog of War)
│   │   ├── ai/             #   Couche IA (personnalités, mémoire, décisions, orchestrateur)
│   │   ├── services/       #   Client Mistral + boucle de jeu (tick)
│   │   ├── presenters.py   #   Données d'affichage du plateau
│   │   ├── views.py        #   Pages + API JSON
│   │   └── tests/          #   Tests unitaires et d'API
│   ├── night_time/         # Actions de nuit (NightAction)
│   ├── voting/             # Votes de jour (Vote)
│   ├── AI_log/             # Journal des appels LLM (AICallLog)
│   ├── accounts/           # Comptes (réservé, vide pour l'instant)
│   ├── templates/          # base.html + game/start.html + game/village.html
│   ├── static/game/        # live.js (polling / actions) + live.css
│   └── manage.py
└── README.md
```

## ⚙️ Prérequis

- **Python 3.12+** (requis par Django 6.1)
- Une **clé API Mistral** (offre gratuite suffisante) — facultative, voir le mode hors ligne
- Un navigateur moderne (avec connexion Internet pour Tailwind CDN & Google Fonts)

Dépendances (`requirements.txt`) : `Django 6.1`, `mistralai`, `httpx`, `python-dotenv`.

## 🚀 Installation (première fois)

Depuis la racine du dépôt :

```bash
# 1. Créer et activer l'environnement virtuel
python3 -m venv .venv
source .venv/bin/activate

# 2. Installer les dépendances
pip install -r requirements.txt

# 3. Configurer la clé Mistral
cp .env.example .env
# puis éditer .env et renseigner MISTRAL_API_KEY

# 4. Créer la base de données
cd loup-garou
python manage.py migrate
```

Le fichier `.env` (à la racine du dépôt, ignoré par git) est chargé
automatiquement au démarrage par `settings.py` :

| Variable | Description |
|---|---|
| `MISTRAL_API_KEY` | Clé API Mistral (obligatoire pour des IA « vivantes ») |
| `MISTRAL_MODEL` | Modèle utilisé (défaut : `ministral-3b-2512`) |

Les variables déjà définies dans l'environnement restent prioritaires sur le `.env`.

## ▶️ Lancer une partie

```bash
# 1. Activer l'environnement virtuel (à refaire à chaque session)
source .venv/bin/activate

# 2. Entrer dans le projet Django
cd loup-garou

# 3. (Optionnel) Créer un superutilisateur pour l'admin
python manage.py createsuperuser

# 4. Démarrer le serveur de développement
python manage.py runserver
```

Puis ouvrir **http://127.0.0.1:8000/** : saisir son nom sur l'écran de départ
et cliquer sur **« Entrer dans le village »**. Le rôle est tiré au hasard.
Une partie est liée à la session du navigateur (pas de compte nécessaire) ;
le bouton « Quitter » ramène à l'écran de départ.

> 💡 En mode `DEBUG`, l'écran de départ propose un menu **« Rôle (mode DEBUG) »**
> pour forcer son rôle (loup, voyante, sorcière, villageois) et tester chaque
> interface nocturne.

### Mode hors ligne / sans IA

| Variable | Effet |
|---|---|
| `AI_BACKEND=fake` | N'appelle pas Mistral : les IA jouent avec leur repli procédural (phrases de secours de leur personnalité). Pratique sans clé API. |
| `AI_ORCHESTRATOR=0` | Désactive complètement les IA (elles n'agissent plus ; les phases avancent au timer). |

```bash
AI_BACKEND=fake python manage.py runserver
```

## 🛠️ Commandes utiles

| Commande | Description |
|---|---|
| `python manage.py runserver` | Lance le serveur de développement |
| `python manage.py runserver 8080` | Lance le serveur sur un autre port |
| `python manage.py migrate` | Applique les migrations de la base |
| `python manage.py makemigrations` | Génère les migrations après modification des modèles |
| `python manage.py createsuperuser` | Crée un compte admin (`/admin/`) |
| `python manage.py check` | Vérifie la configuration du projet |
| `python manage.py test` | Lance les tests (sans réseau, l'orchestrateur IA est désactivé par défaut) |

L'admin Django (`/admin/`) permet d'inspecter les parties, joueurs, messages,
actions de nuit, votes et journaux d'appels IA.

## 🔌 API JSON (utilisée par `static/game/live.js`)

| Méthode | Route | Description |
|---|---|---|
| `GET` | `/` | Écran de départ, ou plateau si une partie est en cours |
| `POST` | `/partie/nouvelle` | Crée une partie (`name`, `role` en DEBUG) |
| `POST` | `/partie/quitter` | Quitte la partie en cours |
| `GET` | `/api/partie/etat?since=<id>` | État vu par l'humain + messages après `since` (fait aussi avancer la partie) |
| `POST` | `/api/partie/message` | `{"text": "...", "channel": "PUBLIC" \| "WOLVES"}` |
| `POST` | `/api/partie/vote` | `{"target_id": <id>}` ou `null` pour un vote blanc |
| `POST` | `/api/partie/nuit` | `{"action": "seer" \| "wolf", "target_id": <id>}` ou `{"action": "witch", "heal": true, "kill_target_id": <id>}` |

Toutes les actions sont validées par l'arbitre du moteur (`game.engine.actions`) :
une action illégale renvoie une erreur 400 avec un message explicite.

## 🤖 Agents IA

### Les 6 personnalités (`game/ai/personas.py`)

Le Stratège · La Mauvaise Joueuse · Le Cynique · La Paranoïaque · La Diplomate · L'Impulsif

Chaque personnalité fournit un caractère injecté dans le prompt système, une
température de génération et des phrases de secours dans son ton.

## 🧩 Fichiers principaux

| Fichier | Rôle |
|---|---|
| `loup-garou/templates/base.html` | Thème médiéval (parchemin, bois, or, cire) |
| `loup-garou/templates/game/start.html` | Écran de départ (nouvelle partie) |
| `loup-garou/templates/game/village.html` | Plateau, chat, interfaces de nuit et modales |
| `loup-garou/static/game/live.js` | Polling de l'API et envoi des actions du joueur |
| `loup-garou/game/views.py` | Pages et API JSON |
| `loup-garou/game/presenters.py` | Données d'affichage construites depuis la vue autorisée |
| `loup-garou/game/engine/` | Règles, création de partie, actions, résolution, state machine |
| `loup-garou/game/ai/` | Personnalités, prompts, mémoire, décisions, orchestrateur |
| `loup-garou/game/services/` | Client Mistral et boucle de jeu |
