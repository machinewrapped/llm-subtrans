"""Model ID resolution must not be blocked by an unavailable model list.

Concrete providers cannot be imported by the unit suites (see tests/ProviderImportGuard.py),
so these checks live in the integration suite with the model lookup mocked out.
"""
from unittest.mock import patch

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Providers.Provider_OpenRouter import OpenRouterProvider
from PySubtrans.Providers.Provider_Requesty import RequestyProvider
from PySubtrans.SettingsType import SettingsType

MODEL_ID_PROVIDERS = (OpenRouterProvider, RequestyProvider)


class TestProviderModelIds(LoggedTestCase):
    """A failed model lookup must not stop a translation client being created."""

    def test_client_creation_survives_a_failed_model_lookup(self) -> None:
        """A lookup failure leaves a saved model ID usable instead of aborting translation."""
        for provider_class in MODEL_ID_PROVIDERS:
            provider = provider_class(SettingsType({'api_key': 'test-key', 'model': 'test-model-id'}))

            with patch.object(provider_class, '_populate_model_cache', side_effect=RuntimeError("offline")):
                client = provider.GetTranslationClient(SettingsType({'instructions': 'Translate the subtitles.'}))

            self.assertLoggedIsNotNone(f"{provider_class.__name__} client created", client)
            self.assertLoggedEqual(
                f"{provider_class.__name__} saved model passed through",
                'test-model-id',
                client.settings.get_str('model'))

    def test_display_name_still_resolves_from_a_populated_cache(self) -> None:
        """A populated cache still maps a display name to its model ID."""
        provider = OpenRouterProvider(SettingsType({'api_key': 'test-key', 'model': 'Gemini Flash'}))
        provider._cached_models = {'Google': {'Gemini Flash': 'google/gemini-flash'}}

        with patch.object(OpenRouterProvider, '_populate_model_cache'):
            model_id = provider._get_model_id('Gemini Flash')

        self.assertLoggedEqual('display name resolved to model ID', 'google/gemini-flash', model_id)
