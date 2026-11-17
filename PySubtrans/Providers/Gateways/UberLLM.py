from PySubtrans.Providers.Gateways.GatewayDefinition import GatewayDefinition
from PySubtrans.Providers.Gateways.GatewayProvider import GatewayProvider
from PySubtrans.Providers.Gateways.ModelCatalogue import FamilySource, ModelCatalogue

UBERLLM = GatewayDefinition(
    name="UberLLM",
    env_prefix="UBERLLM",
    server_address="https://api.uberllm.dev/",
    endpoint="v1/chat/completions",
    default_model="deepseek/deepseek-v4.1-flash",
    default_family="deepseek",
    api_key_url="https://uberllm.dev/signup",
    homepage_url="https://uberllm.dev/",
    privacy_url="https://uberllm.dev/privacy",
    terms_url="https://uberllm.dev/terms",
    models_url="https://uberllm.dev/models",
    description="""
    <p>UberLLM exposes models from many providers through an OpenAI-compatible API, with prepaid pay-as-you-go credit.</p>
    <p>Models are named provider/model (e.g. deepseek/deepseek-v4.1-flash). Ensure your UberLLM account has sufficient credit before translating.</p>
    """,
    # The catalogue marks unavailable models, and lists a few models that return structured decisions rather than text
    catalogue=ModelCatalogue(
        path='v1/models',
        family_source=FamilySource.IdPrefix,
        required_fields={'output_modalities': ['text'], 'available': True},
        excluded_patterns=(r'guard',),
    ),
)

class UberLLMProvider(GatewayProvider):
    definition = UBERLLM
