import logging
import os

from PySubtrans.Helpers.Localization import _
from PySubtrans.Options import env_float, env_int
from PySubtrans.Providers.Clients.APIRouteClient import APIRouteClient
from PySubtrans.SettingsType import GuiSettingsType, SettingsType
from PySubtrans.TranslationClient import TranslationClient
from PySubtrans.TranslationProvider import TranslationProvider

class APIRouteProvider(TranslationProvider):
    name = "API Route"

    default_model = "gpt-6.1-sol"

    information = """
    <p>API Route is a paid OpenAI-compatible gateway for chat models.</p>
    <p>Select a model available to your account. Model IDs are preserved as returned by the authenticated catalogue.</p>
    <p>See the <a href="https://www.api-route.com/docs/quickstart">setup guide</a> and <a href="https://www.api-route.com/pricing">pricing</a>.</p>
    """

    information_noapikey = """
    <p>To use this provider you need <a href="https://www.api-route.com/api-keys">an API Route API key</a>.</p>
    """

    def __init__(self, settings : SettingsType):
        super().__init__(self.name, SettingsType({
            'api_key': settings.get_str('api_key', os.getenv('API_ROUTE_API_KEY')),
            'use_default_model': settings.get_bool('use_default_model', False),
            "server_address": settings.get_str('server_address', os.getenv('API_ROUTE_SERVER_ADDRESS', "https://global.api-route.com/")),
            'stream_responses': settings.get_bool('stream_responses', os.getenv('API_ROUTE_STREAM_RESPONSES', "True") == "True"),
            'model_family': settings.get_str('model_family', os.getenv('API_ROUTE_MODEL_FAMILY', "API Route")),
            "model": settings.get_str('model', os.getenv('API_ROUTE_MODEL', self.default_model)),
            'max_tokens': settings.get_int('max_tokens', env_int('API_ROUTE_MAX_TOKENS', 0)),
            'temperature': settings.get_float('temperature', env_float('API_ROUTE_TEMPERATURE', 0.0)),
            'rate_limit': settings.get_float('rate_limit', env_float('API_ROUTE_RATE_LIMIT')),
            'proxy': settings.get_str('proxy') or os.getenv('API_ROUTE_PROXY'),
            'reuse_client': settings.get_bool('reuse_client', True),
        }))

        self.refresh_when_changed = ['api_key', 'server_address', 'model', 'model_family', 'use_default_model']
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
        Returns a list of available model families for API Route
        """
        available_families = sorted(self._cached_models.keys()) if self._cached_models else []
        valid_families : list[str] = [family for family in available_families if isinstance(family, str)]
        if self.model_family is not None and self.model_family not in valid_families:
            valid_families = [self.model_family] + valid_families
        return valid_families

    @property
    def model_family(self) -> str|None:
        return self.settings.get_str( 'model_family', "API Route")

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
        Returns a new instance of the API Route client
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

            logging.debug(f"API Route using model ID: {client_settings.get('model')}")

        return APIRouteClient(client_settings)

    def GetOptions(self, settings : SettingsType) -> GuiSettingsType:
        """
        Returns a dictionary of options for the API Route provider
        """
        options = {
            'api_key': (str, _( "An API Route API key is required to use this provider (https://www.api-route.com/api-keys)")),
            'use_default_model': (bool, _( "Use the default model and hide advanced model options")),
        }

        if not self.api_key:
            return options

        if not settings.get_bool('use_default_model'):
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
                options['model_family'] = ([_("Unable to retrieve models")], _( "Check API key and try again"))

        if self.use_default_model or self.model_list.known:
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
            logging.debug("No API Route API key provided")
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

    def _populate_model_cache(self) -> None:
        """Load distinct OpenAI-compatible chat IDs from the authenticated catalogue."""
        if not self.api_key or self._cached_models or not self.server_address:
            return

        # Use the existing sanctioned lazy httpx pattern from CustomClient and the gateway providers.
        # Keeping HTTP dependencies out of module scope avoids slowing provider registration.
        import httpx

        try:
            url = self.server_address.rstrip('/') + '/v1/models'
            with httpx.Client(timeout=20, proxy=self.settings.get_str('proxy') or None) as client:
                result = client.get(url, headers={'Authorization': f'Bearer {self.api_key}'})
                result.raise_for_status()
                data = result.json()
                rows = data.get('data') if isinstance(data, dict) else None
                if not isinstance(rows, list):
                    raise ValueError(_("Unable to parse server response as a model list"))

                ids : set[str] = set()
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    model_id = row.get('id')
                    if not isinstance(model_id, str) or not model_id.strip():
                        continue
                    model_id = model_id.strip()
                    endpoints = row.get('supported_endpoint_types')
                    if isinstance(endpoints, list):
                        if 'openai' not in endpoints or any(endpoint in endpoints for endpoint in ('image-generation', 'video-generation')):
                            continue
                    # Some generated-media rows advertise only 'openai', so endpoint metadata alone is insufficient.
                    name = model_id.rsplit('/', 1)[-1].lower()
                    if name.startswith(('gpt-image', 'dall-e', 'imagen', 'nano-banana', 'sora', 'veo', 'seedance', 'flux')) or 'image-preview' in name:
                        continue
                    ids.add(model_id)

                self._all_model_list = sorted(ids)
                self._cached_models = {"API Route": {model_id: model_id for model_id in self._all_model_list}} if ids else {}
        except Exception as error:
            logging.error(_("Unable to retrieve available models: {error}").format(error=str(error)))
            raise

    def _get_model_id(self, display_name : str) -> str:
        """
        Convert display name back to model ID for API calls
        """
        if not display_name:
            return display_name

        # A failed lookup must not block translation: an unresolvable name is
        # passed through unchanged, so an already valid model ID still works.
        try:
            self._populate_model_cache()
        except Exception as e:
            logging.debug(_("Unable to resolve model ID for {model}: {error}").format(model=display_name, error=str(e)))
            return display_name

        for models in self._cached_models.values():
            if display_name in models:
                return models[display_name]

        # Return the model ID if found, otherwise return the display name as-is
        return display_name
