import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from game.services import mistral_client
from game.services.mistral_client import (
    DEFAULT_MODEL,
    MistralConfigurationError,
    MistralGameClient,
)


class MistralEnvironmentTests(SimpleTestCase):
    """La clé et le modèle viennent de .env, sauf s'ils sont forcés."""

    def setUp(self):
        # Environnement vierge (sans les vraies variables du poste) et .env temporaire.
        clean_env = {k: v for k, v in os.environ.items() if not k.startswith("MISTRAL_")}
        env_patch = mock.patch.dict(os.environ, clean_env, clear=True)
        env_patch.start()
        self.addCleanup(env_patch.stop)

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.env_file = Path(tmp.name) / ".env"
        file_patch = mock.patch.object(mistral_client, "ENV_FILE", self.env_file)
        file_patch.start()
        self.addCleanup(file_patch.stop)

    def write_env(self, text):
        self.env_file.write_text(text, encoding="utf-8")

    def test_model_and_key_are_read_from_env_file(self):
        self.write_env("MISTRAL_API_KEY=cle-du-fichier\nMISTRAL_MODEL=modele-du-fichier\n")
        client = MistralGameClient()
        self.assertEqual(client.model, "modele-du-fichier")
        self.assertEqual(client._api_key, "cle-du-fichier")

    def test_spaces_around_equal_sign_are_accepted(self):
        self.write_env("MISTRAL_API_KEY = cle-espacee\nMISTRAL_MODEL = modele-espace\n")
        client = MistralGameClient()
        self.assertEqual(client.model, "modele-espace")
        self.assertEqual(client._api_key, "cle-espacee")

    def test_environment_variables_win_over_env_file(self):
        self.write_env("MISTRAL_API_KEY=cle-du-fichier\nMISTRAL_MODEL=modele-du-fichier\n")
        os.environ["MISTRAL_MODEL"] = "modele-force"
        os.environ["MISTRAL_API_KEY"] = "cle-forcee"
        client = MistralGameClient()
        self.assertEqual(client.model, "modele-force")
        self.assertEqual(client._api_key, "cle-forcee")

    def test_explicit_arguments_win_over_everything(self):
        self.write_env("MISTRAL_API_KEY=cle-du-fichier\nMISTRAL_MODEL=modele-du-fichier\n")
        client = MistralGameClient(api_key="cle-argument", model="modele-argument")
        self.assertEqual(client.model, "modele-argument")
        self.assertEqual(client._api_key, "cle-argument")

    def test_default_model_when_missing_or_empty(self):
        for content in ("MISTRAL_API_KEY=cle\n", "MISTRAL_API_KEY=cle\nMISTRAL_MODEL=\n"):
            with self.subTest(content=content):
                os.environ.pop("MISTRAL_MODEL", None)
                self.write_env(content)
                self.assertEqual(MistralGameClient().model, DEFAULT_MODEL)

    def test_missing_env_file_falls_back_to_default_model(self):
        self.assertFalse(self.env_file.exists())
        self.assertEqual(MistralGameClient().model, DEFAULT_MODEL)

    def test_missing_key_fails_on_first_call_not_on_construction(self):
        self.write_env("MISTRAL_MODEL=modele\n")
        client = MistralGameClient()
        with self.assertRaises(MistralConfigurationError):
            client._get_client()

    def test_key_from_env_file_reaches_the_sdk(self):
        self.write_env("MISTRAL_API_KEY=cle-du-fichier\n")
        with mock.patch("mistralai.Mistral") as sdk:
            MistralGameClient()._get_client()
        self.assertEqual(sdk.call_args.kwargs["api_key"], "cle-du-fichier")

    def test_env_file_is_not_read_when_everything_is_explicit(self):
        with mock.patch.object(mistral_client, "load_environment") as load:
            MistralGameClient(model="m", client=SimpleNamespace())
        load.assert_not_called()
