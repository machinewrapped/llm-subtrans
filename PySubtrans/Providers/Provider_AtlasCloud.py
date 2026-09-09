import json
import logging
import os

import httpx

from PySubtrans.Helpers.Localization import _
from PySubtrans.Options import env_float, env_int
from PySubtrans.Providers.Clients.AtlasCloudClient import AtlasCloudClient
from PySubtrans.SettingsType import GuiSettingsType, SettingsType
from PySubtrans.TranslationClient import TranslationClient
from PySubtrans.TranslationProvider import TranslationProvider


class AtlasCloudProvider(TranslationProvider):
    """Atlas Cloud translation provider using its OpenAI-compatible API."""

    name = "Atlas Cloud"
    default_model = "openai/gpt-4.1-mini"

    information = """
    <p>Select an <a href="https://www.atlascloud.ai/models">Atlas Cloud model</a> to use as a translator.</p>
    <p>Atlas Cloud exposes models through an OpenAI-compatible API. Models are identified as provider/model.</p>
    """

    information_noapikey = """
    <p>To use this provider you need an <a href="https://www.atlascloud.ai/console/api-keys">Atlas Cloud API key</a>.</p>
    <p>Ensure your Atlas Cloud account has sufficient credit before translating.</p>
    """

    def __init__(self, settings : SettingsType):
        super().__init__(self.name, SettingsType({
            'api_key': settings.get_str('api_key', os.getenv('ATLASCLOUD_API_KEY')),
            'api_base': settings.get_str('api_base', os.getenv('ATLASCLOUD_API_BASE', 'https://api.atlascloud.ai')),
            'model': settings.get_str('model', os.getenv('ATLASCLOUD_MODEL', self.default_model)),
            'max_tokens': settings.get_int('max_tokens', env_int('ATLASCLOUD_MAX_TOKENS', 0)),
            'temperature': settings.get_float('temperature', env_float('ATLASCLOUD_TEMPERATURE', 0.0)),
            'rate_limit': settings.get_float('rate_limit', env_float('ATLASCLOUD_RATE_LIMIT')),
            'reuse_client': settings.get_bool('reuse_client', True),
            'proxy': settings.get_str('proxy') or os.getenv('ATLASCLOUD_PROXY'),
            'stream_responses': settings.get_bool('stream_responses', True),
        }))
        self.refresh_when_changed = ['api_key', 'api_base', 'model']

    @property
    def api_key(self) -> str|None:
        return self.settings.get_str('api_key')

    @property
    def api_base(self) -> str|None:
        return self.settings.get_str('api_base')

    def GetTranslationClient(self, settings : SettingsType) -> TranslationClient:
        client_settings = SettingsType(self.settings.copy())
        client_settings.update(settings)
        return AtlasCloudClient(client_settings)

    def GetOptions(self, settings : SettingsType) -> GuiSettingsType:
        options : GuiSettingsType = {
            'api_key': (str, _("An Atlas Cloud API key is required to use this provider (https://www.atlascloud.ai/console/api-keys)")),
            'api_base': (str, _("The base URL to use for requests (default is https://api.atlascloud.ai)")),
        }

        if self.api_key:
            models = self.available_models
            if models:
                options.update({
                    'model': (models, _("AI model to use as the translator")),
                    'stream_responses': (bool, _("Enable streaming responses for real-time translation updates")),
                    'reuse_client': (bool, _("Reuse connection for multiple requests (otherwise a new connection is established for each)")),
                    'max_tokens': (int, _("Maximum number of output tokens to return in the response.")),
                    'temperature': (float, _("Amount of random variance to add to translations. Generally speaking, none is best")),
                    'rate_limit': (float, _("Maximum API requests per minute.")),
                })
            else:
                options['model'] = ([_('Unable to retrieve models')], _("Check API key and base URL and try again"))

        return options

    def GetAvailableModels(self) -> list[str]:
        """Fetch the current Atlas Cloud model catalog."""
        if not self.api_key:
            logging.debug("No Atlas Cloud API key provided")
            return []

        if not self.api_base:
            logging.debug("No Atlas Cloud API base URL provided")
            return []

        try:
            url = self.api_base.rstrip('/') + '/v1/models'
            headers = {'Authorization': f"Bearer {self.api_key}"}
            proxy_url = self.settings.get_str('proxy')

            with httpx.Client(timeout=20, proxy=proxy_url) as client:
                result = client.get(url, headers=headers)
                if result.is_error:
                    logging.error(_("Error fetching models: {status} {text}").format(
                        status=result.status_code, text=result.text))
                    return []

                try:
                    data = result.json()
                    return sorted(model['id'] for model in data.get('data', []) if model.get('id'))
                except json.JSONDecodeError:
                    logging.error(_("Unable to parse server response as JSON: {response_text}").format(
                        response_text=result.text))
                    return []
        except httpx.HTTPError as error:
            logging.error(_("Unable to retrieve available models: {error}").format(error=str(error)))
            return []

    def GetInformation(self) -> str:
        if not self.api_key:
            return self.information_noapikey
        return self.information

    def ValidateSettings(self) -> bool:
        if not self.api_key:
            self.validation_message = _("API Key is required")
            return False
        return True

    def _allow_multithreaded_translation(self) -> bool:
        return self.settings.get_float('rate_limit', 0.0) == 0.0
