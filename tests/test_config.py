import os
import unittest
from unittest.mock import patch

from src.config import ProviderConfig


class ConfigTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        dotenv = patch("src.config.load_dotenv")
        self.load_dotenv = dotenv.start()
        self.addCleanup(dotenv.stop)

    def test_missing_credentials(self):
        with self.assertRaisesRegex(ValueError, "OPENAI_API_KEY or GROQ_API_KEY"):
            ProviderConfig.from_env()

    def test_openai_defaults(self):
        os.environ["OPENAI_API_KEY"] = "openai-test"
        config = ProviderConfig.from_env()
        self.assertEqual((config.api_key, config.base_url, config.model),
                         ("openai-test", "https://api.openai.com/v1", "gpt-4o-mini"))
        self.assertNotIn("openai-test", repr(config))

    def test_groq_defaults(self):
        os.environ["GROQ_API_KEY"] = "groq-test"
        config = ProviderConfig.from_env()
        self.assertEqual(config.api_key, "groq-test")
        self.assertEqual(config.base_url, "https://api.groq.com/openai/v1")
        self.assertEqual(config.model, "llama-3.3-70b-versatile")

    def test_blank_dotenv_overrides_use_provider_defaults(self):
        os.environ.update(OPENAI_API_KEY="openai-test", OPENAI_BASE_URL="", MODEL=" ")
        config = ProviderConfig.from_env()
        self.assertEqual(config.base_url, "https://api.openai.com/v1")
        self.assertEqual(config.model, "gpt-4o-mini")

    def test_openai_key_wins_and_overrides_apply(self):
        os.environ.update(OPENAI_API_KEY="openai-test", GROQ_API_KEY="groq-test",
                          OPENAI_BASE_URL="http://localhost:11434/v1", MODEL="local-model")
        config = ProviderConfig.from_env()
        self.assertEqual((config.api_key, config.base_url, config.model),
                         ("openai-test", "http://localhost:11434/v1", "local-model"))

    def test_groq_explicit_overrides(self):
        os.environ.update(GROQ_API_KEY="groq-test", MODEL="custom", OPENAI_BASE_URL="https://example.com/v1")
        config = ProviderConfig.from_env()
        self.assertEqual(config.model, "custom")
        self.assertEqual(config.base_url, "https://example.com/v1")

    def test_dotenv_path_and_shell_precedence(self):
        os.environ["OPENAI_API_KEY"] = "shell-key"
        self.assertEqual(ProviderConfig.from_env().api_key, "shell-key")
        args, kwargs = self.load_dotenv.call_args
        self.assertEqual(args[0].name, ".env")
        self.assertEqual(kwargs, {"override": False})
