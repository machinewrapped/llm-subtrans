import unittest
from unittest.mock import MagicMock, patch

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Providers.Clients.AtlasCloudClient import AtlasCloudClient
from PySubtrans.Providers.Provider_AtlasCloud import AtlasCloudProvider
from PySubtrans.SettingsType import SettingsType
from PySubtrans.TranslationProvider import TranslationProvider


class TestAtlasCloudProvider(LoggedTestCase):
    """Tests for the Atlas Cloud provider and client."""

    def test_provider_registered(self):
        providers = TranslationProvider.get_providers()
        self.assertLoggedIn("Atlas Cloud in providers", "Atlas Cloud", providers)

    def test_provider_creates_chat_client(self):
        settings = SettingsType({
            'api_key': 'test-key',
            'model': 'openai/gpt-4.1-mini',
        })
        provider = AtlasCloudProvider(settings)
        client = provider.GetTranslationClient(SettingsType({'instructions': 'Translate the subtitles.'}))

        self.assertLoggedIsInstance("client type", client, AtlasCloudClient)
        self.assertLoggedEqual("API server", 'https://api.atlascloud.ai', client.server_address)
        self.assertLoggedEqual("chat completions endpoint", '/v1/chat/completions', client.endpoint)
        self.assertLoggedEqual("selected model", 'openai/gpt-4.1-mini', client.model)

    @patch('PySubtrans.Providers.Provider_AtlasCloud.httpx.Client')
    def test_available_models_uses_atlas_catalog(self, mock_client_class : MagicMock):
        response = MagicMock()
        response.is_error = False
        response.json.return_value = {
            'data': [
                {'id': 'openai/gpt-4.1-mini'},
                {'id': 'anthropic/claude-sonnet-4'},
            ]
        }
        mock_client_class.return_value.__enter__.return_value.get.return_value = response
        provider = AtlasCloudProvider(SettingsType({'api_key': 'test-key'}))

        models = provider.GetAvailableModels()

        self.assertLoggedEqual(
            "sorted Atlas model catalog",
            ['anthropic/claude-sonnet-4', 'openai/gpt-4.1-mini'],
            models,
        )
        mock_client_class.return_value.__enter__.return_value.get.assert_called_once_with(
            'https://api.atlascloud.ai/v1/models',
            headers={'Authorization': 'Bearer test-key'},
        )

    def test_missing_api_key_fails_validation(self):
        with patch.dict('os.environ', {}, clear=True):
            provider = AtlasCloudProvider(SettingsType())

        self.assertLoggedEqual("settings are invalid without API key", False, provider.ValidateSettings())
        self.assertLoggedEqual("validation message", "API Key is required", provider.validation_message)


if __name__ == '__main__':
    unittest.main()
