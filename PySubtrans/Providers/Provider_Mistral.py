import importlib.util
import logging
import os

import httpx

from PySubtrans.Options import SettingsType, env_float
from PySubtrans.SettingsType import GuiSettingsType, SettingsType

if not importlib.util.find_spec("mistralai"):
    from PySubtrans.Helpers.Localization import _
    logging.debug(_("Mistral SDK is not installed. Mistral provider will not be available"))
else:
    try:
        import mistralai

        from PySubtrans.Helpers.Localization import _
        from PySubtrans.Providers.Clients.MistralClient import MistralClient
        from PySubtrans.TranslationClient import TranslationClient
        from PySubtrans.TranslationProvider import TranslationProvider

        class MistralProvider(TranslationProvider):
            name = "Mistral"

            default_model = "mistral-small-latest"

            information = """
            <p>Select the <a href="https://docs.mistral.ai/getting-started/models/models_overview/">model</a> to use as a translator.</p>
            """

            information_noapikey = """
            <p>To use this provider you need <a href="https://console.mistral.ai/api-keys/">a Mistral API key</a>.</p>
            <p>Note that Mistral provide many specialised models that are unlikely to be useful as translators.</p>
            """

            def __init__(self, settings : SettingsType):
                super().__init__(self.name, SettingsType({
                    "api_key": settings.get_str('api_key', os.getenv('MISTRAL_API_KEY')),
                    "server_url": settings.get_str('server_url', os.getenv('MISTRAL_SERVER_URL')),
                    "model": settings.get_str('model', os.getenv('MISTRAL_MODEL', self.default_model)),
                    'temperature': settings.get_float('temperature', env_float('MISTRAL_TEMPERATURE', 0.0)),
                    'rate_limit': settings.get_float('rate_limit', env_float('MISTRAL_RATE_LIMIT')),
                    'proxy': settings.get_str('proxy') or os.getenv('MISTRAL_PROXY'),
                }))

                self.refresh_when_changed = ['api_key', 'server_url', 'model']

            @property
            def api_key(self) -> str|None:
                return self.settings.get_str( 'api_key')

            @property
            def server_url(self) -> str|None:
                return self.settings.get_str( 'server_url')

            def GetTranslationClient(self, settings : SettingsType) -> TranslationClient:
                client_settings = SettingsType(self.settings.copy())
                client_settings.update(settings)
                client_settings.update({
                    'supports_conversation': True,
                    'supports_system_messages': True,
                    'supports_system_messages_for_retry': False,
                    'supports_system_prompt': False
                    })
                return MistralClient(client_settings)

            def GetOptions(self, settings : SettingsType) -> GuiSettingsType:
                options : GuiSettingsType = {
                    'api_key': (str, _("A Mistral API key is required to use this provider (https://console.mistral.ai/api-keys/)")),
                    'server_url': (str, _("The base URL to use for requests (default is https://api.mistral.ai)")),
                }

                if self.api_key:
                    models = self.available_models
                    if models:
                        options.update({
                            'model': (models, "AI model to use as the translator"),
                            'temperature': (float, _("Amount of random variance to add to translations. Generally speaking, none is best")),
                            'rate_limit': (float, _("Maximum API requests per minute."))
                        })

                    else:
                        options['model'] = (["Unable to retrieve models"], _("Check API key and base URL and try again"))

                return options

            def GetAvailableModels(self) -> list[str]:
                """
                Returns a list of possible values for the model
                """
                try:
                    if not self.api_key:
                        logging.debug("No Mistral API key provided")
                        return []

                    proxy_url = self.settings.get_str('proxy')
                    http_client = httpx.Client(proxy=proxy_url) if proxy_url else None
                    client = mistralai.Mistral(
                        api_key=self.api_key,
                        server_url=self.server_url or None,
                        client=http_client
                    )
                    response = client.models.list()

                    if not response or not response.data:
                        return []

                    model_list = [ model.id for model in response.data]

                    return sorted(model_list)

                except Exception as e:
                    logging.error(_("Unable to retrieve available AI models: {error}").format(error=str(e)))
                    return []

            def GetInformation(self) -> str:
                if not self.api_key:
                    return self.information_noapikey
                return self.information

            def ValidateSettings(self) -> bool:
                """
                Validate the settings for the provider
                """
                if not self.api_key:
                    self.validation_message = _("API Key is required")
                    return False

                return True

            def _allow_multithreaded_translation(self) -> bool:
                """
                If user has set a rate limit we can't make multiple requests at once
                """
                if self.settings.get_float( 'rate_limit', 0.0) != 0.0:
                    return False

                return True

    except ImportError:
        from PySubtrans.Helpers.Localization import _
        logging.info(_("Mistral SDK not installed. Mistral provider will not be available"))