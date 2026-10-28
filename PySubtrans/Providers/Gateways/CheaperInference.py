from PySubtrans.Providers.Gateways.GatewayDefinition import GatewayDefinition
from PySubtrans.Providers.Gateways.GatewayProvider import GatewayProvider
from PySubtrans.Providers.Gateways.ModelCatalogue import FamilySource, ModelCatalogue

CHEAPER_INFERENCE = GatewayDefinition(
    name="Cheaper Inference",
    env_prefix="CHEAPER_INFERENCE",
    server_address="https://api.cheaperinference.com/",
    endpoint="v1/chat/completions",
    default_model="gpt-5.4-mini",
    default_family="OpenAI",
    api_key_url="https://cheaperinference.com/signup",
    models_url="https://cheaperinference.com/markets",
    description="""
    <p>Cheaper Inference is an OpenAI-compatible LLM gateway that provides access to models from many different makers.</p>
    <p>Models use bare IDs without a vendor prefix (e.g. gpt-5.4-mini, claude-sonnet-5), and the maker is read from the catalogue.</p>
    """,
    # The catalogue also lists media models and text models without chat completions
    catalogue=ModelCatalogue(
        path='v1/models',
        family_source=FamilySource.Field,
        family_field='owned_by',
        required_fields={'type': 'text'},
        required_list_members={'supported_endpoints': '/v1/chat/completions'},
    ),
)

class CheaperInferenceProvider(GatewayProvider):
    definition = CHEAPER_INFERENCE
