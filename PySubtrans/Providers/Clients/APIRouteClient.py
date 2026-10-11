from PySubtrans.Providers.Clients.CustomClient import CustomClient
from PySubtrans.SettingsType import SettingsType

class APIRouteClient(CustomClient):
    """
    Handles chat communication with API Route to request translations
    """
    def __init__(self, settings : SettingsType):
        settings.setdefault('supports_system_messages', True)
        settings.setdefault('supports_conversation', True)
        settings.setdefault('supports_streaming', True)
        settings.setdefault('server_address', 'https://global.api-route.com/')
        settings.setdefault('endpoint', 'v1/chat/completions')
        super().__init__(settings)
