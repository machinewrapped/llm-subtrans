from PySubtrans.Providers.Gateways.GatewayDefinition import GatewayDefinition
from PySubtrans.Providers.Gateways.GatewayProvider import GatewayProvider
from PySubtrans.Providers.Gateways.ModelCatalogue import FamilySource, ModelCatalogue

RUNCRATE = GatewayDefinition(
    name="Runcrate",
    env_prefix="RUNCRATE",
    server_address="https://api.runcrate.ai/",
    endpoint="v1/chat/completions",
    default_model="deepseek-ai/DeepSeek-V4.1-Flash",
    default_family="deepseek-ai",
    api_key_url="https://runcrate.ai/dashboard/api-keys",
    homepage_url="https://www.runcrate.ai/",
    privacy_url="https://www.runcrate.ai/privacy",
    terms_url="https://www.runcrate.ai/terms",
    models_url="https://runcrate.ai/inference",
    description="""
    <p>Runcrate serves open-weight models through an OpenAI-compatible API.</p>
    <p>Models are named maker/model (e.g. deepseek-ai/DeepSeek-V4.1-Flash). Ensure your Runcrate account has sufficient credit before translating.</p>
    """,
    # The catalogue also lists speech, embedding, image and moderation models, which cannot translate
    catalogue=ModelCatalogue(
        path='v1/models',
        family_source=FamilySource.IdPrefix,
        required_fields={'output_modalities': ['text']},
        excluded_patterns=(r'whisper', r'voxtral', r'guard', r'safety'),
    ),
)

class RuncrateProvider(GatewayProvider):
    definition = RUNCRATE
