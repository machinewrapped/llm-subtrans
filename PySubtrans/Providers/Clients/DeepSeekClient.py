from PySubtrans.Helpers.Localization import _
from PySubtrans.Providers.Clients.CustomClient import CustomClient
from PySubtrans.SettingsType import SettingsType

class DeepSeekClient(CustomClient):
    """
    Handles chat communication with DeepSeek to request translations using CustomClient logic
    """
    def __init__(self, settings: SettingsType):
        settings['supports_system_messages'] = True
        settings['supports_conversation'] = True
        settings['supports_reasoning'] = True
        settings['supports_streaming'] = True
        settings.setdefault('server_address', settings.get_str('api_base', 'https://api.deepseek.com'))
        settings.setdefault('endpoint', '/v1/chat/completions')
        super().__init__(settings)
