import importlib.util
import unittest

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.SettingsType import SettingsType


@unittest.skipUnless(
    importlib.util.find_spec("litellm"),
    "litellm is not installed"
)
class TestLiteLLMProvider(LoggedTestCase):
    """Tests for the LiteLLM provider and client."""

    def test_provider_registered(self):
        """LiteLLMProvider should be discoverable via TranslationProvider.get_providers()"""
        from PySubtrans.TranslationProvider import TranslationProvider

        providers = TranslationProvider.get_providers()
        self.assertLoggedIn("LiteLLM in providers", "LiteLLM", providers)

    def test_provider_creates_client(self):
        """LiteLLMProvider.GetTranslationClient should return a LiteLLMClient"""
        from PySubtrans.Providers.Clients.LiteLLMClient import LiteLLMClient
        from PySubtrans.Providers.Provider_LiteLLM import LiteLLMProvider

        settings = SettingsType({
            'model': 'openai/gpt-4o',
            'api_key': 'sk-test',
            'instructions': 'Translate the subtitles.',
        })
        provider = LiteLLMProvider(settings)
        client = provider.GetTranslationClient(settings)
        self.assertLoggedIsInstance("client type", client, LiteLLMClient)

    def test_provider_available_models(self):
        """LiteLLMProvider should return a non-empty model list"""
        from PySubtrans.Providers.Provider_LiteLLM import LiteLLMProvider

        settings = SettingsType({'model': 'openai/gpt-4o'})
        provider = LiteLLMProvider(settings)
        models = provider.GetAvailableModels()
        self.assertLoggedGreater("model count", len(models), 0)

    def test_provider_options(self):
        """LiteLLMProvider.GetOptions should return expected option keys"""
        from PySubtrans.Providers.Provider_LiteLLM import LiteLLMProvider

        settings = SettingsType({'model': 'openai/gpt-4o'})
        provider = LiteLLMProvider(settings)
        options = provider.GetOptions(settings)
        self.assertLoggedIn("model option", "model", options)
        self.assertLoggedIn("api_key option", "api_key", options)

    def test_provider_multithreaded_default(self):
        """LiteLLMProvider should allow multithreaded by default"""
        from PySubtrans.Providers.Provider_LiteLLM import LiteLLMProvider

        settings = SettingsType({'model': 'openai/gpt-4o'})
        provider = LiteLLMProvider(settings)
        self.assertLoggedEqual(
            "multithreaded allowed",
            True,
            provider.allow_multithreaded_translation
        )

    def test_provider_multithreaded_with_rate_limit(self):
        """LiteLLMProvider should disallow multithreaded when rate limit is set"""
        from PySubtrans.Providers.Provider_LiteLLM import LiteLLMProvider

        settings = SettingsType({'model': 'openai/gpt-4o', 'rate_limit': 10.0})
        provider = LiteLLMProvider(settings)
        self.assertLoggedEqual(
            "multithreaded disallowed with rate limit",
            False,
            provider.allow_multithreaded_translation
        )


if __name__ == '__main__':
    unittest.main()
