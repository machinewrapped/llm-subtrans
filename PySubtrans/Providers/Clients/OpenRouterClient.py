from PySubtrans.Helpers.Localization import _
from PySubtrans.Providers.Clients.CustomClient import CustomClient
from PySubtrans.SettingsType import SettingsType

class OpenRouterClient(CustomClient):
    """
    Handles chat communication with OpenRouter to request translations
    """
    def __init__(self, settings: SettingsType):
        settings.setdefault('supports_system_messages', True)
        settings.setdefault('supports_conversation', True)
        settings.setdefault('server_address', 'https://openrouter.ai/api/')
        settings.setdefault('endpoint', '/v1/chat/completions')
        settings.setdefault('additional_headers', {
            'HTTP-Referer': 'https://github.com/machinewrapped/llm-subtrans',
            'X-Title': 'LLM-Subtrans'
            })
        super().__init__(settings)
