from PySubtrans.Providers.Clients.CustomClient import CustomClient
from PySubtrans.SettingsType import SettingsType

class OpperClient(CustomClient):
    """
    Handles chat communication with Opper to request translations
    """
    def __init__(self, settings: SettingsType):
        settings.setdefault('supports_system_messages', True)
        settings.setdefault('supports_conversation', True)
        settings.setdefault('supports_streaming', True)
        settings.setdefault('server_address', 'https://api.opper.ai/')
        settings.setdefault('endpoint', 'v3/compat/chat/completions')
        super().__init__(settings)
