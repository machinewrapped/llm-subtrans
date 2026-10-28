from unittest.mock import patch

import httpx

from PySubtrans.Helpers.Attribution import APP_ATTRIBUTION_HEADERS
from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Providers.Clients.CustomClient import CustomClient
from PySubtrans.Providers.Gateways.CheaperInference import CHEAPER_INFERENCE
from PySubtrans.Providers.Gateways.GatewayProvider import GatewayProvider
from PySubtrans.Providers.Gateways.ModelCatalogue import FamilySource, ModelCatalogue
from PySubtrans.Providers.Gateways.Opper import OPPER, OpperProvider
from PySubtrans.Providers.Gateways.Requesty import REQUESTY, RequestyProvider
from PySubtrans.SettingsType import SettingsType
from PySubtrans.TranslationProvider import ProviderKind, TranslationProvider


def _mock_catalogue(client_class, url : str, payload) -> None:
    """Make the patched httpx.Client return a catalogue response."""
    client = client_class.return_value.__enter__.return_value
    client.get.return_value = httpx.Response(200, json=payload, request=httpx.Request('GET', url))


class TestGatewayRegistration(LoggedTestCase):
    """Gateways are registered from their definitions, the base class is not."""

    def test_gateways_are_registered_by_definition_name(self) -> None:
        providers = TranslationProvider.get_providers()

        self.assertLoggedIs("Requesty registered", RequestyProvider, providers.get(REQUESTY.name))
        self.assertLoggedIs("Opper registered", OpperProvider, providers.get(OPPER.name))
        self.assertLoggedNotIn("base class not registered", GatewayProvider, list(providers.values()))

    def test_gateways_report_gateway_kind(self) -> None:
        for definition in (REQUESTY, OPPER):
            self.assertLoggedEqual(f"{definition.name} kind", ProviderKind.Gateway, TranslationProvider.get_provider_kind(definition.name))


class TestGatewayCatalogue(LoggedTestCase):
    """Catalogue definitions group and filter models without gateway-specific code."""

    def test_id_prefix_groups_by_maker(self) -> None:
        provider = RequestyProvider(SettingsType({'api_key': 'test-key', 'model_family': 'openai'}))

        with patch('httpx.Client') as client_class:
            _mock_catalogue(client_class, 'https://router.requesty.ai/v1/models', {'data': [
                {'id': 'openai/gpt-4o-mini'},
                {'id': 'anthropic/claude-sonnet-4-5'},
                {'id': 'standalone-model'},
            ]})
            models = provider.GetAvailableModels()
            client = client_class.return_value.__enter__.return_value
            kwargs = client.get.call_args.kwargs

        self.assertLoggedEqual("openai family models", ['gpt-4o-mini'], models)
        self.assertLoggedEqual("families", ['Generic', 'anthropic', 'openai'], provider.available_model_families)
        self.assertLoggedEqual("display name resolves to ID", 'anthropic/claude-sonnet-4-5', provider._get_model_id('claude-sonnet-4-5'))
        self.assertLoggedEqual("catalogue authenticated", 'Bearer test-key', kwargs['headers'].get('Authorization'))

    def test_field_family_with_required_fields(self) -> None:
        provider = OpperProvider(SettingsType({'api_key': 'test-key', 'model_family': 'google'}))

        with patch('httpx.Client') as client_class:
            _mock_catalogue(client_class, 'https://api.opper.ai/v3/models', {'models': [
                {'model': 'gemini-3.8-flash', 'pooled': True, 'type': 'llm', 'maker': {'slug': 'google'}},
                {'model': 'gemini-3.8-flash', 'pooled': True, 'type': 'llm', 'maker': {'slug': 'google'}},
                {'model': 'gemini-route-eu', 'pooled': False, 'type': 'llm', 'maker': {'slug': 'google'}},
                {'model': 'imagen-5', 'pooled': True, 'type': 'image', 'maker': {'slug': 'google'}},
                {'model': 'claude-sonnet-4-6', 'pooled': True, 'type': 'llm', 'maker': {'slug': 'anthropic'}},
            ]})
            models = provider.GetAvailableModels()
            client = client_class.return_value.__enter__.return_value
            kwargs = client.get.call_args.kwargs

        self.assertLoggedEqual("google pooled chat models", ['gemini-3.8-flash'], models)
        self.assertLoggedEqual("all models listed once", ['claude-sonnet-4-6', 'gemini-3.8-flash'], provider.all_available_models)
        self.assertLoggedEqual("catalogue query", {'limit': 2000}, kwargs['params'])
        self.assertLoggedEqual("public catalogue sends no key", {}, kwargs['headers'])

    def test_single_family_with_excluded_prefixes(self) -> None:
        catalogue = ModelCatalogue(path='v1/models', family_source=FamilySource.Single, excluded_prefixes=('gpt-image', 'veo'))

        models_by_family, all_models = catalogue.Parse({'data': [
            {'id': 'gpt-6.1-sol'},
            {'id': 'GPT-Image-2'},
            {'id': 'veo-3'},
            {'id': ''},
            None,
        ]}, "Example Gateway")

        self.assertLoggedEqual("one family named after the gateway", ["Example Gateway"], list(models_by_family.keys()))
        self.assertLoggedEqual("excluded models removed", ['gpt-6.1-sol'], all_models)

    def test_cheaper_inference_keeps_only_chat_models(self) -> None:
        """Keep models that support chat even when another endpoint is preferred."""
        models_by_family, all_models = CHEAPER_INFERENCE.catalogue.Parse({'data': [
            {'id': 'gpt-5.4-mini', 'type': 'text', 'owned_by': 'OpenAI',
             'supported_endpoints': ['/v1/chat/completions', '/v1/responses']},
            {'id': 'claude-sonnet-5', 'type': 'text', 'owned_by': 'Anthropic',
             'endpoint': '/v1/messages', 'supported_endpoints': ['/v1/messages', '/v1/chat/completions']},
            {'id': 'o3-pro', 'type': 'text', 'owned_by': 'OpenAI',
             'supported_endpoints': ['/v1/responses']},
            {'id': 'legacy-text', 'type': 'text', 'owned_by': 'OpenAI'},
            {'id': 'invalid-endpoints', 'type': 'text', 'owned_by': 'OpenAI',
             'supported_endpoints': '/v1/chat/completions'},
            {'id': 'image-model', 'type': 'image', 'owned_by': 'OpenAI',
             'supported_endpoints': ['/v1/chat/completions']},
        ]}, CHEAPER_INFERENCE.name)

        self.assertLoggedEqual("chat-capable model IDs", ['claude-sonnet-5', 'gpt-5.4-mini'], all_models)
        self.assertLoggedEqual("OpenAI chat models", {'gpt-5.4-mini': 'gpt-5.4-mini'}, models_by_family.get('OpenAI'))
        self.assertLoggedEqual("Anthropic chat models", {'claude-sonnet-5': 'claude-sonnet-5'}, models_by_family.get('Anthropic'))


class TestGatewayFamilySelector(LoggedTestCase):
    """The family selector is hidden only when there is nothing else to choose."""

    def test_selector_shown_when_saved_family_is_missing(self) -> None:
        provider = RequestyProvider(SettingsType({'api_key': 'test-key', 'model_family': 'openai'}))
        provider._cached_models = {'anthropic': {'claude-sonnet-4-5': 'anthropic/claude-sonnet-4-5'}}

        options = provider.GetOptions(provider.settings)

        self.assertLoggedIn("family selector offered", 'model_family', options)

    def test_selector_hidden_for_single_matching_family(self) -> None:
        provider = RequestyProvider(SettingsType({'api_key': 'test-key', 'model_family': 'anthropic'}))
        provider._cached_models = {'anthropic': {'claude-sonnet-4-5': 'anthropic/claude-sonnet-4-5'}}

        options = provider.GetOptions(provider.settings)

        self.assertLoggedNotIn("no family selector", 'model_family', options)
        self.assertLoggedIn("model selector offered", 'model', options)


class TestGatewayClient(LoggedTestCase):
    """The client is configured from the gateway definition."""

    def test_client_uses_definition_endpoint_and_headers(self) -> None:
        provider = RequestyProvider(SettingsType({'api_key': 'test-key', 'use_default_model': True}))
        client = provider.GetTranslationClient(SettingsType({'instructions': 'Translate the subtitles.'}))

        self.assertLoggedIsInstance("client type", client, CustomClient)
        assert isinstance(client, CustomClient)
        self.assertLoggedEqual("default model", REQUESTY.default_model, client.settings.get_str('model'))
        self.assertLoggedEqual("server address", REQUESTY.server_address, client.server_address)
        self.assertLoggedEqual("endpoint", REQUESTY.endpoint, client.endpoint)
        self.assertLoggedEqual("bearer key", 'Bearer test-key', client.headers.get('Authorization'))
        self.assertLoggedEqual("attribution header", APP_ATTRIBUTION_HEADERS['X-Title'], client.headers.get('X-Title'))
        self.assertLoggedTrue("streaming supported", client.supports_streaming)

    def test_client_creation_survives_a_failed_model_lookup(self) -> None:
        """A lookup failure leaves a saved model ID usable instead of aborting translation."""
        gateways = [provider for provider in TranslationProvider.get_providers().values() if issubclass(provider, GatewayProvider)]
        self.assertLoggedGreater("registered gateways", len(gateways), 0)

        for provider_class in gateways:
            provider = provider_class(SettingsType({'api_key': 'test-key', 'model': 'test-model-id'}))

            with patch.object(provider_class, '_populate_model_cache', side_effect=RuntimeError("offline")):
                client = provider.GetTranslationClient(SettingsType({'instructions': 'Translate the subtitles.'}))

            self.assertLoggedEqual(f"{provider_class.name} saved model passed through", 'test-model-id', client.settings.get_str('model'))

    def test_environment_prefix_supplies_defaults(self) -> None:
        with patch.dict('os.environ', {'OPPER_API_KEY': 'environment-key', 'OPPER_MODEL': 'environment-model'}):
            provider = OpperProvider(SettingsType())
            explicit = OpperProvider(SettingsType({'api_key': 'explicit-key'}))

        self.assertLoggedEqual("environment key", 'environment-key', provider.api_key)
        self.assertLoggedEqual("environment model", 'environment-model', provider.selected_model)
        self.assertLoggedEqual("explicit setting wins", 'explicit-key', explicit.api_key)
