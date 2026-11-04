# Loup-Garou

## Client Mistral

Le service `game.services.mistral_client.MistralGameClient` utilise le SDK
Mistral et le modèle `mistral-small-latest` par défaut. La clé API et le modèle
sont configurables via `MISTRAL_API_KEY` et `MISTRAL_MODEL`. Copiez
[`.env.example`](./.env.example) vers `.env` et renseignez votre clé avant
d'utiliser le client. Ne commitez jamais le fichier `.env`.

```python
from game.services.mistral_client import MistralGameClient

client = MistralGameClient()
result = client.get_game_response("Je soupçonne Alice.")
```

Les messages humains sont échappés avant envoi. Le prompt système traite leur
contenu comme non fiable. Le client demande une réponse JSON et refuse toute
réponse qui ne contient pas exactement les champs chaîne `action`, `target`,
`thought` et `message`.

Pour installer les dépendances, exécutez `pip install -r requirements.txt`.
Les tests unitaires du client sont dans `loup-garou/game/tests.py`.
