import importlib.util
import logging

from PySubtrans.Helpers.Localization import _
from PySubtrans.Options import SettingsType, env_str
from PySubtrans.SettingsType import GuiSettingsType, SettingsType

if not importlib.util.find_spec("openai"):
    logging.debug(_("OpenAI SDK is not installed. Azure provider will not be available"))
else:
    try:
        import openai   # type: ignore

        from PySubtrans.Providers.Clients.AzureOpenAIClient import AzureOpenAIClient
        from PySubtrans.TranslationClient import TranslationClient
        from PySubtrans.TranslationProvider import TranslationProvider

        class AzureOpenAiProvider(TranslationProvider):
            name = "Azure"

            information = """
            <p>Azure API-provider.</p>
            <p>To use Azure as a provider you need to provide the name and address of an OpenAI Azure deployment, an API version and API Key.</p>
            """

            def __init__(self, settings : SettingsType):
                super().__init__(self.name, SettingsType({
                    "api_key": settings.get_str('api_key', env_str('AZURE_API_KEY')),
                    "api_base": settings.get_str('api_base', env_str('AZURE_API_BASE')),
                    "api_version": settings.get_str('api_version', env_str('AZURE_API_VERSION')),
                    "deployment_name": settings.get_str('deployment_name', env_str('AZURE_DEPLOYMENT_NAME')),
                }))

                self.refresh_when_changed = ['api_key', 'api_base', 'api_version', 'deployment_name']

            @property
            def api_key(self) -> str|None:
                return self.settings.get_str( 'api_key')

            @property
            def api_base(self) -> str|None:
                return self.settings.get_str( 'api_base')

            @property
            def api_version(self) -> str|None:
                return self.settings.get_str( 'api_version')

            @property
            def deployment_name(self) -> str|None:
                return self.settings.get_str( 'deployment_name')

            def GetTranslationClient(self, settings : SettingsType) -> TranslationClient:
                client_settings = SettingsType(self.settings.copy())
                client_settings.update(settings)
                client_settings.update({
                    'supports_conversation': True,
                    'supports_system_messages': True
                    })
                return AzureOpenAIClient(client_settings)

            def GetOptions(self, settings : SettingsType) -> GuiSettingsType:
                options : GuiSettingsType = {
                    'api_key': (str, _("An Azure API key is required")),
                    'api_version': (str, _("An Azure API version is required")),
                    'deployment_name': (str, _("An Azure API deployment name is required")),
                    'api_base': (str, _("The Azure API base URL to use for requests.")),
                }

                return options

            def GetInformation(self) -> str:
                information = self.information
                if not self.ValidateSettings():
                    information = information + f"<p>{self.validation_message}</p>"
                return information

            def GetAvailableModels(self) -> list[str]:
                return []

            def ValidateSettings(self) -> bool:
                """
                Validate the settings for the provider
                """
                if not self.api_key:
                    self.validation_message = _("API Key is required")
                    return False

                if not self.api_version:
                    self.validation_message = "Azure API version is required"
                    return False

                if not self.deployment_name:
                    self.validation_message = "Azure deployment name is required"
                    return False

                if not self.api_base:
                    self.validation_message = "Azure API base is required"
                    return False

                return True

            def _allow_multithreaded_translation(self) -> bool:
                """
                Assume the Aazure provider can handle multiple requests
                """
                return True

    except ImportError:
        logging.info(_("OpenAI SDK not installed. Azure provider will not be available"))
