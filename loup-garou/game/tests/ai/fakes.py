import json
from types import SimpleNamespace

from game.services.mistral_client import MistralGameClient


class FakeMistral:
    """Imite ``client.chat.complete`` du SDK Mistral, sans réseau."""

    def __init__(self, payload=None, *, error=None, prompt_tokens=900, completion_tokens=60):
        self.payload = payload
        self.error = error
        self.calls = []
        self.usage = SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
        self.chat = SimpleNamespace(complete=self.complete)

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        content = self.payload if isinstance(self.payload, str) else json.dumps(self.payload)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=self.usage,
        )


def fake_client(payload=None, **kwargs):
    sdk = FakeMistral(payload, **kwargs)
    return MistralGameClient(model="fake-model", client=sdk), sdk


def answer(action, target="", message="", thought="Je réfléchis."):
    return {"action": action, "target": target, "message": message, "thought": thought}
