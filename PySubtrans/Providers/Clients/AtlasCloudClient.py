from PySubtrans.Providers.Clients.CustomClient import CustomClient
from PySubtrans.SettingsType import SettingsType


class AtlasCloudClient(CustomClient):
    """Handles OpenAI-compatible chat requests to Atlas Cloud."""

    def __init__(self, settings : SettingsType):
        settings['supports_system_messages'] = True
        settings['supports_conversation'] = True
        settings['supports_streaming'] = True
        settings.setdefault('server_address', settings.get_str('api_base', 'https://api.atlascloud.ai'))
        settings.setdefault('endpoint', '/v1/chat/completions')
        super().__init__(settings)
