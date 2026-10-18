from unittest.mock import patch

import httpx

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Providers.Gateways.APIRoute import API_ROUTE, APIRouteProvider
from PySubtrans.SettingsType import SettingsType


class TestAPIRouteProvider(LoggedTestCase):
    """API Route offers only chat models from its catalogue."""

    def test_discovery_keeps_chat_ids_and_filters_generated_media(self) -> None:
        rows = [
            {'id': 'gpt-6.1-sol', 'supported_endpoint_types': ['openai']},
            {'id': 'gpt-6.1-sol'},
            {'id': 'claude-sonnet-4-6', 'supported_endpoint_types': ['anthropic', 'openai']},
            {'id': 'native-anthropic-only', 'supported_endpoint_types': ['anthropic']},
            {'id': 'gpt-image-2.5', 'supported_endpoint_types': ['image-generation', 'openai']},
            {'id': 'gemini-3-flash-image-preview', 'supported_endpoint_types': ['openai']},
            {'id': 'bytedance/seedance-2', 'supported_endpoint_types': ['openai']},
            {'id': 'veo-3'},
            {'id': ''},
            {'id': None},
            None,
        ]
        response = httpx.Response(200, json={'data': rows}, request=httpx.Request('GET', 'https://global.api-route.com/v1/models'))
        provider = APIRouteProvider(SettingsType({'api_key': 'test-key'}))

        with patch('httpx.Client') as client_class:
            client_class.return_value.__enter__.return_value.get.return_value = response
            models = provider.GetAvailableModels()

        self.assertLoggedEqual("chat models", ['claude-sonnet-4-6', 'gpt-6.1-sol'], models)
        self.assertLoggedEqual("all models", models, provider.all_available_models)
        self.assertLoggedEqual("one family named after the gateway", [API_ROUTE.name], provider.available_model_families)
