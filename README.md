# 🐺 Le Loup-Garou de Thiercelieux — Plateau de jeu

Front du projet Loup-Garou : le plateau de jeu dans un style médiéval classique
(parchemin, bois, or et cire à sceller), avec les 7 places du village disposées
en cercle autour de l'emblème de **Thiercelieux**.

> Le plateau est **statique** : aucune partie n'est simulée. Il présente la
> disposition initiale du village (composition, rôles secrets, rappel des phases).

## 📁 Structure du projet

```
loup-garou/
├── .venv/                  # Environnement virtuel Python
├── loup-garou/             # Projet Django
│   ├── loupgarou/          # Configuration du projet (settings, urls)
│   ├── game/               # App du plateau de jeu (vue, urls)
│   ├── templates/          # base.html + templates du jeu
│   └── manage.py
└── README.md
```

## ⚙️ Prérequis

- **Python 3.12+**
- **Django 6.1** (installé dans le venv)
- Un navigateur moderne (avec connexion Internet pour Tailwind CDN & Google Fonts)

## 🚀 Installation (première fois)

Depuis la racine du dépôt :

```bash
# 1. Créer l'environnement virtuel
python3 -m venv .venv

# 2. L'activer
source .venv/bin/activate

# 3. Installer Django
pip install Django
```

## ▶️ Lancer le plateau de jeu

```bash
# 1. Activer l'environnement virtuel (à refaire à chaque session)
source .venv/bin/activate

# 2. Entrer dans le projet Django
cd loup-garou

# 3. (Premier lancement uniquement) Créer/appliquer les migrations
python manage.py migrate

# 4. (Optionnel) Créer un superutilisateur pour l'admin
python manage.py createsuperuser

# 5. Démarrer le serveur de développement
python manage.py runserver
```

Puis ouvrir **http://127.0.0.1:8000/** dans le navigateur : c'est le plateau de jeu.

> 💡 Astuce : sans activer le venv, on peut aussi utiliser
> `.venv/bin/python manage.py runserver` depuis la racine.

## 🛠️ Commandes utiles

| Commande | Description |
|---|---|
| `python manage.py runserver` | Lance le serveur de développement (front) |
| `python manage.py runserver 8080` | Lance le serveur sur un autre port |
| `python manage.py migrate` | Applique les migrations de la base |
| `python manage.py makemigrations` | Génère les migrations après modification des modèles |
| `python manage.py createsuperuser` | Crée un compte admin (`/admin/`) |
| `python manage.py check` | Vérifie la configuration du projet |
| `python manage.py test` | Lance les tests |

## 🎨 Ce que contient le plateau

- **Plateau central circulaire** : les 7 habitants autour de la place du village.
- **Joueur humain** mis en avant (sceau « Vous », rôle révélé pour lui seul).
- **Six personnalités IA** dont les rôles restent cachés (Fog of War : `?`).
- **Pan « Composition du village »** : monstres et habitants (loups, voyante, sorcière, villageois).
- **Pan « Votre carte »** : rôle, description et potions.
- **Rappel statique du déroulement** : nuit, jour, vote — sans aucun interaction.
- **Responsive** : dispositions circulaires en desktop, grille en mobile.

## 🤖 Service IA Mistral

Le service `game.services.mistral_client.MistralGameClient` effectue les appels
SDK dans un thread afin de ne pas bloquer la boucle asynchrone. Chaque appel est
limité à 3,5 secondes ; en cas de timeout, d'erreur API ou de réponse invalide,
il renvoie une phrase de repli adaptée à la personnalité et au type d'action.
Tous les appels aboutis ou en échec sont enregistrés dans `AI_log.AICallLog`,
avec les tokens d'entrée et de sortie disponibles.

```python
from AI_log.models import CallType
from game.services.mistral_client import MistralGameClient

client = MistralGameClient()
response = await client.get_game_response(
    message,
    game=game,
    player=ai_player,
    call_type=CallType.CHAT,
)
```

Le plateau et ses vues restent statiques pour l'instant : ce service asynchrone
est prêt à être appelé par une future boucle de jeu, mais n'est pas encore
raccordé à une vue HTTP.

## 🧩 Fichiers principaux du front

| Fichier | Rôle |
|---|---|
| `loup-garou/templates/base.html` | Thème médiéval (parchemin, bois, or, cire) |
| `loup-garou/templates/game/village.html` | Le plateau de jeu lui-même (board + panneaux) |
| `loup-garou/game/views.py` | Données statiques du plateau (7 joueurs, composition, phases) |
| `loup-garou/game/urls.py` | Route `/` vers le plateau |
