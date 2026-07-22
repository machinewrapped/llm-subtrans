import importlib.util
import unittest

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.SettingsType import SettingsType

# Keep top-level imports clean, but safely handle when LiteLLM is not installed
if importlib.util.find_spec("litellm"):
    from PySubtrans.Providers.Clients.LiteLLMClient import LiteLLMClient
    from PySubtrans.Providers.Provider_LiteLLM import LiteLLMProvider
    from PySubtrans.TranslationProvider import TranslationProvider
else:
    LiteLLMClient = None
    LiteLLMProvider = None
    TranslationProvider = None


@unittest.skipUnless(
    importlib.util.find_spec("litellm"),
    "litellm is not installed"
)
class TestLiteLLMProvider(LoggedTestCase):
    """Tests for the LiteLLM provider and client."""

    def test_provider_registered(self):
        """LiteLLMProvider should be discoverable via TranslationProvider.get_providers()"""
        assert TranslationProvider is not None
        providers = TranslationProvider.get_providers()
        self.assertLoggedIn("LiteLLM in providers", "LiteLLM", providers)

    def test_provider_creates_client(self):
        """LiteLLMProvider.GetTranslationClient should return a LiteLLMClient"""
        assert LiteLLMProvider is not None
        assert LiteLLMClient is not None
        settings = SettingsType({
            'model': 'openai/gpt-4o',
            'api_key': 'sk-test',
            'instructions': 'Translate the subtitles.',
        })
        provider = LiteLLMProvider(settings)
        client = provider.GetTranslationClient(settings)
        self.assertLoggedIsInstance("client type", client, LiteLLMClient)

    def test_provider_available_models_returns_empty(self):
        """LiteLLMProvider model list should be empty since input is free-text"""
        assert LiteLLMProvider is not None
        settings = SettingsType({'model': 'openai/gpt-4o'})
        provider = LiteLLMProvider(settings)
        models = provider.GetAvailableModels()
        self.assertLoggedEqual("model list empty", [], models)


if __name__ == '__main__':
    unittest.main()
