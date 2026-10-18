from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum

from PySubtrans.Providers.Gateways.ModelCatalogue import ModelCatalogue

class GatewayProtocol(Enum):
    """
    The API protocol a gateway uses for translation requests.
    """
    ChatCompletions = 'chat_completions'    # OpenAI-style /chat/completions with bearer authentication

@dataclass(frozen=True)
class GatewayDefinition:
    """
    Everything that distinguishes one gateway from another.
    """
    name : str
    env_prefix : str                                # e.g. 'REQUESTY' for REQUESTY_API_KEY
    server_address : str
    endpoint : str
    default_model : str
    default_family : str
    api_key_url : str
    models_url : str
    description : str                               # HTML paragraph(s) shown in the provider information
    catalogue : ModelCatalogue
    protocol : GatewayProtocol = GatewayProtocol.ChatCompletions
    additional_headers : Mapping[str, str] = field(default_factory=dict)
