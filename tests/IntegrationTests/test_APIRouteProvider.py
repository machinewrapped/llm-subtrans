import logging
import os
from unittest.mock import patch

import httpx

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Providers.Clients.APIRouteClient import APIRouteClient
from PySubtrans.Providers.Provider_APIRoute import APIRouteProvider
from PySubtrans.SettingsType import SettingsType


class TestAPIRouteProvider(LoggedTestCase):
    """API Route discovery must preserve chat IDs and isolate credentials."""

    def test_environment_defaults_and_explicit_settings(self) -> None:
        with patch.dict(os.environ, {'API_ROUTE_API_KEY': 'environment-key', 'API_ROUTE_MODEL': 'environment-model'}):
            provider = APIRouteProvider(SettingsType())
            explicit = APIRouteProvider(SettingsType({'api_key': 'explicit-key', 'model': 'explicit-model'}))
        self.assertLoggedEqual('environment key', 'environment-key', provider.api_key)
        self.assertLoggedEqual('environment model', 'environment-model', provider.settings.get_str('model'))
        self.assertLoggedEqual('explicit key', 'explicit-key', explicit.api_key)
        self.assertLoggedEqual('explicit model', 'explicit-model', explicit.settings.get_str('model'))

    def test_discovery_preserves_distinct_chat_ids_and_filters_generated_media(self) -> None:
        rows = [
            {'id': 'gpt-6.1-sol', 'supported_endpoint_types': ['openai']},
            {'id': 'gpt-6.1-sol'},
            {'id': 'claude-sonnet-4-6', 'supported_endpoint_types': ['anthropic', 'openai']},
            {'id': 'native-anthropic-only', 'supported_endpoint_types': ['anthropic']},
            {'id': 'gpt-image-2.5', 'supported_endpoint_types': ['image-generation', 'openai']},
            {'id': 'bytedance/seedance-2', 'supported_endpoint_types': ['openai']},
            {'id': 'veo-3'},
            {'id': ''},
            {'id': None},
            None,
        ]
        response = httpx.Response(200, json={'data': rows}, request=httpx.Request('GET', 'https://global.api-route.com/v1/models'))
        provider = APIRouteProvider(SettingsType({'api_key': 'test-key'}))
        with patch('httpx.Client') as client_class:
            client = client_class.return_value.__enter__.return_value
            client.get.return_value = response
            models = provider.GetAvailableModels()
            client.get.assert_called_once_with('https://global.api-route.com/v1/models', headers={'Authorization': 'Bearer test-key'})
        self.assertLoggedEqual('chat models', ['claude-sonnet-4-6', 'gpt-6.1-sol'], models)
        self.assertLoggedEqual('all models retain IDs', models, provider.all_available_models)

    def test_missing_key_does_not_discover_models(self) -> None:
        provider = APIRouteProvider(SettingsType({'api_key': ''}))
        with patch('httpx.Client') as client_class:
            models = provider.GetAvailableModels()
            client_class.assert_not_called()
        self.assertLoggedEqual('empty list without credentials', [], models)
        self.assertLoggedEqual('settings reject missing key', False, provider.ValidateSettings())

    def test_client_uses_default_model_and_authenticated_compat_endpoint(self) -> None:
        provider = APIRouteProvider(SettingsType({'api_key': 'test-key', 'use_default_model': True}))
        client = provider.GetTranslationClient(SettingsType({'instructions': 'Translate the subtitles.'}))
        self.assertLoggedIsInstance('API Route client', client, APIRouteClient)
        assert isinstance(client, APIRouteClient)
        self.assertLoggedEqual('default model', 'gpt-6.1-sol', client.settings.get_str('model'))
        self.assertLoggedEqual('server root', 'https://global.api-route.com/', client.settings.get_str('server_address'))
        self.assertLoggedEqual('compat endpoint', 'v1/chat/completions', client.settings.get_str('endpoint'))
        self.assertLoggedEqual('dedicated bearer key', 'Bearer test-key', client.headers.get('Authorization'))
        self.assertLoggedEqual('streaming supported', True, client.settings.get_bool('supports_streaming'))

    def test_discovery_failure_keeps_saved_model_usable(self) -> None:
        provider = APIRouteProvider(SettingsType({'api_key': 'test-key', 'model': 'saved-model-id'}))
        with patch.object(APIRouteProvider, '_populate_model_cache', side_effect=RuntimeError('offline')):
            client = provider.GetTranslationClient(SettingsType({'instructions': 'Translate the subtitles.'}))
        self.assertLoggedEqual('saved model survives failed discovery', 'saved-model-id', client.settings.get_str('model'))

    def test_malformed_catalogue_is_reported_without_caching(self) -> None:
        response = httpx.Response(200, json={'unexpected': []}, request=httpx.Request('GET', 'https://global.api-route.com/v1/models'))
        provider = APIRouteProvider(SettingsType({'api_key': 'test-key'}))
        with patch('httpx.Client') as client_class:
            client_class.return_value.__enter__.return_value.get.return_value = response
            with self.assertLogs(level=logging.ERROR):
                with self.assertRaises(ValueError):
                    provider.GetAvailableModels()
        self.assertLoggedEqual('failed catalogue does not populate cache', {}, provider._cached_models)
