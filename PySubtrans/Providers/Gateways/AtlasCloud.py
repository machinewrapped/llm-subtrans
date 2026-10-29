from PySubtrans.Providers.Gateways.GatewayDefinition import GatewayDefinition
from PySubtrans.Providers.Gateways.GatewayProvider import GatewayProvider
from PySubtrans.Providers.Gateways.ModelCatalogue import FamilySource, ModelCatalogue

ATLAS_CLOUD = GatewayDefinition(
    name="Atlas Cloud",
    env_prefix="ATLASCLOUD",
    server_address="https://api.atlascloud.ai/",
    endpoint="v1/chat/completions",
    default_model="openai/gpt-6-luna",
    default_family="openai",
    api_key_url="https://www.atlascloud.ai/console/api-keys",
    models_url="https://www.atlascloud.ai/models",
    description="""
    <p>Atlas Cloud exposes models from many providers through an OpenAI-compatible API.</p>
    <p>Models are named provider/model (e.g. openai/gpt-6-luna). Ensure your Atlas Cloud account has sufficient credit before translating.</p>
    """,
    catalogue=ModelCatalogue(
        path='v1/models',
        family_source=FamilySource.IdPrefix,
        excluded_patterns=(r'\bimage\b',),       # Image generation models, e.g. gpt-image-2, gemini-3-pro-image
    ),
)

class AtlasCloudProvider(GatewayProvider):
    definition = ATLAS_CLOUD
