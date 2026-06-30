import json
import logging
import os
import httpx

from PySubtrans.Helpers.Localization import _
from PySubtrans.Options import SettingsType, env_float, env_int
from PySubtrans.Providers.Clients.RequestyClient import RequestyClient
from PySubtrans.SettingsType import GuiSettingsType, SettingsType
from PySubtrans.TranslationClient import TranslationClient
from PySubtrans.TranslationProvider import TranslationProvider

class RequestyProvider(TranslationProvider):
    name = "Requesty"

    default_model = "openai/gpt-4o-mini"

    information = """
    <p>Select the <a href="https://app.requesty.ai/models">model</a> to use as a translator.</p>
    <p>Requesty is an OpenAI-compatible LLM gateway that provides access to many different AI models from various providers.</p>
    <p>Models are named provider/model (e.g. openai/gpt-4o-mini, anthropic/claude-sonnet-4-5).</p>
    <p>Models are grouped by provider family to make selection easier.</p>
    """

    information_noapikey = """
    <p>To use this provider you need <a href="https://app.requesty.ai/api-keys">a Requesty API key</a>.</p>
    <p>Note that you must have credit to use Requesty models.</p>
    """

    def __init__(self, settings : SettingsType):
        super().__init__(self.name, SettingsType({
            'api_key': settings.get_str('api_key', os.getenv('REQUESTY_API_KEY')),
            'use_default_model': settings.get_bool('use_default_model', False),
            "server_address": settings.get_str('server_address', os.getenv('REQUESTY_SERVER_ADDRESS', "https://router.requesty.ai/")),
            'stream_responses': settings.get_bool('stream_responses', os.getenv('REQUESTY_STREAM_RESPONSES', "True") == "True"),
            'model_family': settings.get_str('model_family', os.getenv('REQUESTY_MODEL_FAMILY', "openai")),
            "model": settings.get_str('model', os.getenv('REQUESTY_MODEL', self.default_model)),
            'max_tokens': settings.get_int('max_tokens', env_int('REQUESTY_MAX_TOKENS', 0)),
            'temperature': settings.get_float('temperature', env_float('REQUESTY_TEMPERATURE', 0.0)),
            'rate_limit': settings.get_float('rate_limit', env_float('REQUESTY_RATE_LIMIT')),
            'proxy': settings.get_str('proxy') or os.getenv('REQUESTY_PROXY'),
            'reuse_client': settings.get_bool('reuse_client', True),
        }))

        self.refresh_when_changed = ['api_key', 'model', 'model_family', 'use_default_model']
        self._all_model_list = []
        self._cached_models : dict[str, dict[str,str]] = {}

    @property
    def use_default_model(self) -> bool:
        return self.settings.get_bool( 'use_default_model', True)

    @property
    def api_key(self) -> str|None:
        return self.settings.get_str( 'api_key')

    @property
    def server_address(self) -> str|None:
        return self.settings.get_str( 'server_address')

    @property
    def available_model_families(self) -> list[str]:
        """
        Returns a list of available provider families for the Requesty API
        """
        available_families = sorted(self._cached_models.keys()) if self._cached_models else []
        valid_families : list[str] = [family for family in available_families if isinstance(family, str)]
        if self.model_family is not None and self.model_family not in valid_families:
            valid_families = [self.model_family] + valid_families
        return valid_families

    @property
    def model_family(self) -> str|None:
        return self.settings.get_str( 'model_family', "openai")

    @property
    def all_available_models(self) -> list[str]:
        """
        Returns all available models for the provider, including those currently filtered out
        """
        if not self._cached_models:
            self._populate_model_cache()

        return self._all_model_list

    def GetTranslationClient(self, settings : SettingsType) -> TranslationClient:
        """
        Returns a new instance of the Requesty client
        """
        client_settings = SettingsType(self.settings.copy())
        client_settings.update(settings)

        if self.use_default_model:
            client_settings['model'] = self.default_model
        else:
            # Convert display name back to model ID
            model = self.settings.get_str( 'model')
            selected_model = client_settings.get_str('model', default=model)
            if not selected_model:
                selected_model = self.selected_model or self.default_model
            else:
                client_settings['model'] = self._get_model_id(selected_model)

            logging.debug(f"Requesty using model ID: {client_settings.get('model')}")

        return RequestyClient(client_settings)

    def GetOptions(self, settings : SettingsType) -> GuiSettingsType:
        """
        Returns a dictionary of options for the Requesty provider
        """
        options = {
            'api_key': (str, _( "A Requesty API key is required to use this provider (https://app.requesty.ai/api-keys)")),
            'use_default_model': (bool, _( "Use the default model and hide advanced model options")),
        }

        if not self.api_key:
            return options

        if not settings.get_bool('use_default_model'):
            # First populate cached models if needed
            self._populate_model_cache()

            if self._cached_models:
                options.update({
                    'model_family': (self.available_model_families, _( "Model family/provider to choose from")),
                })

                # Add model selector if family is chosen
                model_family : str|None = settings.get_str('model_family') or self.model_family
                if model_family:
                    family_models = self._cached_models.get(model_family)
                    if family_models:
                        model_display_names : list[str] = list(family_models.keys())
                        options['model'] = (model_display_names, _( "AI model to use as the translator"))
                    else:
                        options['model'] = ([_("No models available")], _( "Try a different model family or change filter settings"))
                else:
                    options['model'] = ([_("No models available")], _( "Try a different model family or change filter settings"))
            else:
                options['model_family'] = (["Unable to retrieve models"], _( "Check API key and try again"))

        if self.use_default_model or self.available_models:
            options.update({
                'stream_responses': (bool, _( "Stream translations in realtime as they are generated")),
                'max_tokens': (int, _( "Maximum number of output tokens to return in the response.")),
                'temperature': (float, _( "Amount of random variance to add to translations. Generally speaking, none is best")),
                'rate_limit': (float, _( "Maximum API requests per minute.")),
                'reuse_client': (bool, _( "Reuse connection for multiple requests (otherwise a new connection is established for each)")),
            })

        return options

    def GetAvailableModels(self) -> list[str]:
        """
        Return models for the selected family from cached data
        """
        if not self.api_key:
            logging.debug("No Requesty API key provided")
            return []

        if self.use_default_model:
            # If using default model, return empty list
            return []

        # Ensure cache is populated
        self._populate_model_cache()

        if not self._cached_models:
            logging.warning(_("Cannot retrieve model list, check API key"))
            return []

        family = self.model_family
        if not family:
            return []

        family_models : dict[str,str] = self._cached_models.get(family, {})

        # Return display names sorted
        return sorted(family_models.keys())

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

    def _populate_model_cache(self):
        """
        Fetch and cache models grouped by provider family from the Requesty API.

        Requesty returns OpenAI-shaped model objects with an 'id' field of the
        form 'provider/model' and OpenAI-style capability fields such as
        'context_window' and boolean 'supports_*' flags (which differ from
        OpenRouter's 'context_length' and 'supported_parameters' array).
        """
        if not self.api_key:
            return

        if self._cached_models:
            return  # Cache already populated

        try:
            if not self.server_address:
                logging.debug("No Requesty server address provided")
                return

            url = self.server_address.rstrip('/') + '/v1/models'

            headers = {'Authorization': f"Bearer {self.api_key}"} if self.api_key else {}

            proxy_url = self.settings.get_str('proxy')
            with httpx.Client(timeout=20, proxy=proxy_url) as client:
                result = client.get(url, headers=headers)
                if result.is_error:
                    logging.error(_("Error fetching models: {status} {text}").format(
                        status=result.status_code, text=result.text))
                    return

                try:
                    data = result.json()
                    # Requesty returns models under 'data' (OpenAI-compatible)
                    models_data = data.get('data', data if isinstance(data, list) else [])
                    model_cache : dict[str, dict[str, str]] = {}
                    all_models : list[str] = []

                    for model in models_data:
                        model_id = model.get('id', '')
                        if not model_id:
                            continue

                        all_models.append(model_id)

                        # Family is the provider prefix in the 'provider/model' id
                        model_series, model_name = self._get_model_name(model)

                        if model_series not in model_cache:
                            model_cache[model_series] = {}

                        # Store display name -> model_id mapping
                        display_name = model_name if model_name else model_id
                        model_cache[model_series][display_name] = model_id

                    self._all_model_list = sorted(all_models)
                    self._cached_models = model_cache

                except json.JSONDecodeError:
                    logging.error(_("Unable to parse server response as JSON: {response_text}").format(response_text=result.text))
                    return

        except Exception as e:
            logging.error(_("Unable to retrieve available models: {error}").format(error=str(e)))
            return

    def _get_model_name(self, model : dict) -> tuple[str, str]:
        """
        Split a Requesty model id ('provider/model') into family and model name.
        """
        model_id = model.get('id', '')
        if '/' in model_id:
            model_series, model_name = model_id.split('/', 1)
        else:
            model_series, model_name = ("Generic", model_id)
        return model_series, model_name

    def _get_model_id(self, display_name: str) -> str:
        """
        Convert display name back to model ID for API calls
        """
        if not display_name:
            return display_name

        # Ensure cache is populated
        self._populate_model_cache()

        for family, models in self._cached_models.items(): # type: ignore[unused-variable]
            if display_name in models:
                return models[display_name]

        # Return the model ID if found, otherwise return the display name as-is
        return display_name
