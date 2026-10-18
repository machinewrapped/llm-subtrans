from PySubtrans.Providers.Gateways.GatewayDefinition import GatewayDefinition
from PySubtrans.Providers.Gateways.GatewayProvider import GatewayProvider
from PySubtrans.Providers.Gateways.ModelCatalogue import FamilySource, ModelCatalogue

OPPER = GatewayDefinition(
    name="Opper",
    env_prefix="OPPER",
    server_address="https://api.opper.ai/",
    endpoint="v3/compat/chat/completions",
    default_model="gemini-3.8-flash",
    default_family="google",
    api_key_url="https://platform.opper.ai",
    models_url="https://opper.ai/models",
    description="""
    <p>Opper is an EU-hosted AI gateway with an OpenAI-compatible API, giving access to models from many different providers.</p>
    <p>Models use pool names without a vendor prefix (e.g. gemini-3.8-flash, claude-sonnet-4-6), and Opper picks the route for each request.</p>
    """,
    # The public catalogue lists one entry per route; pooled entries carry the pool name, which is the ID to send
    catalogue=ModelCatalogue(
        path='v3/models',
        list_key='models',
        id_field='model',
        family_source=FamilySource.Field,
        family_field='maker.slug',
        requires_auth=False,
        query={'limit': 2000},
        required_fields={'pooled': True, 'type': 'llm'},
    ),
)

class OpperProvider(GatewayProvider):
    definition = OPPER
