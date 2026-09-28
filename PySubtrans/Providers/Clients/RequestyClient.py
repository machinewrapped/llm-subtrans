from PySubtrans.Helpers.Attribution import APP_ATTRIBUTION_HEADERS
from PySubtrans.Helpers.Localization import _
from PySubtrans.Providers.Clients.CustomClient import CustomClient
from PySubtrans.SettingsType import SettingsType

class RequestyClient(CustomClient):
    """
    Handles chat communication with Requesty to request translations
    """
    def __init__(self, settings: SettingsType):
        settings.setdefault('supports_system_messages', True)
        settings.setdefault('supports_conversation', True)
        settings.setdefault('supports_streaming', True)
        settings.setdefault('server_address', 'https://router.requesty.ai/')
        settings.setdefault('endpoint', 'v1/chat/completions')
        settings.setdefault('additional_headers', dict(APP_ATTRIBUTION_HEADERS))
        super().__init__(settings)
