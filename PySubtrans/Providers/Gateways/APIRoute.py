from typing import Any

from PySubtrans.Providers.Gateways.GatewayDefinition import GatewayDefinition
from PySubtrans.Providers.Gateways.GatewayProvider import GatewayProvider
from PySubtrans.Providers.Gateways.ModelCatalogue import FamilySource, ModelCatalogue

API_ROUTE = GatewayDefinition(
    name="API Route",
    env_prefix="API_ROUTE",
    server_address="https://global.api-route.com/",
    endpoint="v1/chat/completions",
    default_model="gpt-6.1-sol",
    default_family="API Route",
    api_key_url="https://www.api-route.com/api-keys",
    models_url="https://www.api-route.com/pricing",
    description="""
    <p>API Route is a paid OpenAI-compatible gateway for chat models.</p>
    <p>Model IDs are listed as the authenticated catalogue returns them. See the <a href="https://www.api-route.com/docs/quickstart">setup guide</a>.</p>
    """,
    # Generated-media models can be listed with only an OpenAI endpoint, so they are also excluded by name
    catalogue=ModelCatalogue(
        path='v1/models',
        family_source=FamilySource.Single,
        excluded_prefixes=('gpt-image', 'dall-e', 'imagen', 'nano-banana', 'sora', 'veo', 'seedance', 'flux'),
    ),
)

# Endpoint types that mark a model as generating media rather than chat
_MEDIA_ENDPOINT_TYPES = ('image-generation', 'video-generation')

class APIRouteProvider(GatewayProvider):
    definition = API_ROUTE

    def _parse_catalogue(self, data : Any) -> tuple[dict[str, dict[str, str]], list[str]]:
        """
        Offer only models served through the OpenAI-compatible chat endpoint.
        """
        if isinstance(data, dict) and isinstance(data.get('data'), list):
            data = { 'data': [entry for entry in data['data'] if _is_chat_model(entry)] }

        return super()._parse_catalogue(data)

def _is_chat_model(entry : Any) -> bool:
    """
    Whether a catalogue entry can be used for chat completions.
    Entries without endpoint metadata are kept for the name filter to judge.
    """
    if not isinstance(entry, dict):
        return False

    model_id = entry.get('id')
    if isinstance(model_id, str) and 'image-preview' in model_id.lower():
        return False

    endpoints = entry.get('supported_endpoint_types')
    if not isinstance(endpoints, list):
        return True

    return 'openai' in endpoints and not any(endpoint in endpoints for endpoint in _MEDIA_ENDPOINT_TYPES)
