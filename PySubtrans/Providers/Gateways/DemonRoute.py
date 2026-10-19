from PySubtrans.Providers.Gateways.GatewayDefinition import GatewayDefinition
from PySubtrans.Providers.Gateways.GatewayProvider import GatewayProvider
from PySubtrans.Providers.Gateways.ModelCatalogue import FamilySource, ModelCatalogue

DEMONROUTE = GatewayDefinition(
    name="DemonRoute",
    env_prefix="DEMONROUTE",
    server_address="https://api.demonroute.com/",
    endpoint="v1/chat/completions",
    default_model="openai/gpt-oss-120b",
    default_family="openai",
    api_key_url="https://demonroute.com/login",
    models_url="https://demonroute.com/models",
    description="""
    <p>DemonRoute is a prepaid OpenAI-compatible gateway for open-weight models served by third-party hosts.</p>
    <p>Models are named family/model (e.g. openai/gpt-oss-120b). Quality varies across community fine-tunes.</p>
    """,
    catalogue=ModelCatalogue(path='v1/models', family_source=FamilySource.IdPrefix),
)

class DemonRouteProvider(GatewayProvider):
    definition = DEMONROUTE
