from PySubtrans.Helpers.Attribution import APP_ATTRIBUTION_HEADERS
from PySubtrans.Providers.Gateways.GatewayDefinition import GatewayDefinition
from PySubtrans.Providers.Gateways.GatewayProvider import GatewayProvider
from PySubtrans.Providers.Gateways.ModelCatalogue import FamilySource, ModelCatalogue

REQUESTY = GatewayDefinition(
    name="Requesty",
    env_prefix="REQUESTY",
    server_address="https://router.requesty.ai/",
    endpoint="v1/chat/completions",
    default_model="openai/gpt-4o-mini",
    default_family="openai",
    api_key_url="https://app.requesty.ai/api-keys",
    models_url="https://app.requesty.ai/models",
    description="""
    <p>Requesty is an OpenAI-compatible LLM gateway that provides access to many different AI models from various providers.</p>
    <p>Models are named provider/model (e.g. openai/gpt-4o-mini, anthropic/claude-sonnet-4-5).</p>
    """,
    catalogue=ModelCatalogue(path='v1/models', family_source=FamilySource.IdPrefix),
    additional_headers=APP_ATTRIBUTION_HEADERS,
)

class RequestyProvider(GatewayProvider):
    definition = REQUESTY
