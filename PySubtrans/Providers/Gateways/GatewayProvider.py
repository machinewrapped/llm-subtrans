import json
import logging
import os
from typing import Any, ClassVar

from PySubtrans.Helpers.Localization import _
from PySubtrans.Options import env_float, env_int
from PySubtrans.Providers.Clients.CustomClient import CustomClient
from PySubtrans.Providers.Gateways.GatewayDefinition import GatewayDefinition, GatewayProtocol
from PySubtrans.Providers.Gateways.ModelCatalogue import FamilySource
from PySubtrans.SettingsType import GuiSettingsType, SettingsType
from PySubtrans.TranslationClient import TranslationClient
from PySubtrans.TranslationProvider import ProviderKind, TranslationProvider

class GatewayProvider(TranslationProvider):
    """
    Base class for gateways that route requests to models from many makers.

    Each gateway is a subclass that sets `definition`.
    The provider name, default model and settings namespace all come from the definition.
    """
    kind = ProviderKind.Gateway

    definition : ClassVar[GatewayDefinition]
    default_model : ClassVar[str]

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if 'definition' in vars(cls):
            cls.name = cls.definition.name
            cls.default_model = cls.definition.default_model

    def __init__(self, settings : SettingsType):
        definition = self.definition
        prefix = definition.env_prefix

        super().__init__(definition.name, SettingsType({
            'api_key': settings.get_str('api_key', os.getenv(f'{prefix}_API_KEY')),
            'use_default_model': settings.get_bool('use_default_model', False),
            'server_address': settings.get_str('server_address', os.getenv(f'{prefix}_SERVER_ADDRESS', definition.server_address)),
            'stream_responses': settings.get_bool('stream_responses', os.getenv(f'{prefix}_STREAM_RESPONSES', "True") == "True"),
            'model_family': settings.get_str('model_family', os.getenv(f'{prefix}_MODEL_FAMILY', self._default_family)),
            'model': settings.get_str('model', os.getenv(f'{prefix}_MODEL', definition.default_model)),
            'max_tokens': settings.get_int('max_tokens', env_int(f'{prefix}_MAX_TOKENS', 0)),
            'temperature': settings.get_float('temperature', env_float(f'{prefix}_TEMPERATURE', 0.0)),
            'rate_limit': settings.get_float('rate_limit', env_float(f'{prefix}_RATE_LIMIT')),
            'proxy': settings.get_str('proxy') or os.getenv(f'{prefix}_PROXY'),
            'reuse_client': settings.get_bool('reuse_client', True),
        }))

        self.refresh_when_changed = ['api_key', 'model', 'model_family', 'use_default_model']
        self._all_model_list : list[str] = []
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
        Returns a list of available model families for the gateway
        """
        available_families = sorted(self._cached_models.keys()) if self._cached_models else []
        valid_families : list[str] = [family for family in available_families if isinstance(family, str)]
        if self.model_family is not None and self.model_family not in valid_families:
            valid_families = [self.model_family] + valid_families
        return valid_families

    @property
    def model_family(self) -> str|None:
        return self.settings.get_str( 'model_family', self._default_family)

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
        Returns a new client for the gateway's protocol
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

            logging.debug(f"{self.name} using model ID: {client_settings.get('model')}")

        return self._create_client(client_settings)

    def GetOptions(self, settings : SettingsType) -> GuiSettingsType:
        """
        Returns a dictionary of options for the gateway
        """
        options = {
            'api_key': (str, _("An API key from {provider} is required to use this provider ({url})").format(
                provider=self.name, url=self.definition.api_key_url)),
            'use_default_model': (bool, _( "Use the default model and hide advanced model options")),
        }

        if not self.api_key:
            return options

        if not settings.get_bool('use_default_model'):
            if self._cached_models:
                if len(self._cached_models) > 1:
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
            logging.debug(f"No {self.name} API key provided")
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
        definition = self.definition
        if not self.api_key:
            return f'<p>To use this provider you need <a href="{definition.api_key_url}">an API key from {self.name}</a>.</p>'

        information = f'<p>Select the <a href="{definition.models_url}">model</a> to use as a translator.</p>\n{definition.description}'
        if definition.catalogue.family_source != FamilySource.Single:
            information += '\n<p>Models are grouped by model maker to make selection easier.</p>'

        return information

    def ValidateSettings(self) -> bool:
        """
        Validate the settings for the provider
        """
        if not self.api_key:
            self.validation_message = _("API Key is required")
            return False

        return True

    @property
    def _default_family(self) -> str:
        """
        Single-family gateways name their only family after themselves
        """
        if self.definition.catalogue.family_source == FamilySource.Single:
            return self.definition.name
        return self.definition.default_family

    def _create_client(self, settings : SettingsType) -> TranslationClient:
        """
        Create a client that speaks the gateway's protocol
        """
        definition = self.definition
        settings['endpoint'] = definition.endpoint

        match definition.protocol:
            case GatewayProtocol.ChatCompletions:
                settings.setdefault('supports_system_messages', True)
                settings.setdefault('supports_conversation', True)
                settings.setdefault('supports_streaming', True)
                if definition.additional_headers:
                    settings.setdefault('additional_headers', dict(definition.additional_headers))
                return CustomClient(settings)

    def _allow_multithreaded_translation(self) -> bool:
        """
        If user has set a rate limit we can't make multiple requests at once
        """
        if self.settings.get_float( 'rate_limit', 0.0) != 0.0:
            return False

        return True

    def _populate_model_cache(self):
        """
        Fetch the gateway's model catalogue and cache the models grouped by family.
        """
        if not self.api_key:
            return

        if self._cached_models:
            return  # Cache already populated

        try:
            # Sanctioned lazy import: the startup profile attributed about 1.25 seconds to loading httpx through the provider registration path.
            import httpx

            if not self.server_address:
                logging.debug(f"No {self.name} server address provided")
                return

            catalogue = self.definition.catalogue
            url = self.server_address.rstrip('/') + '/' + catalogue.path.lstrip('/')
            headers = {'Authorization': f"Bearer {self.api_key}"} if catalogue.requires_auth else {}

            proxy_url = self.settings.get_str('proxy') or None
            with httpx.Client(timeout=20, proxy=proxy_url) as client:
                result = client.get(url, headers=headers, params=dict(catalogue.query))
                if result.is_error:
                    raise ValueError(_("Error fetching models: {status} {text}").format(
                        status=result.status_code, text=result.text))

                try:
                    data = result.json()
                except json.JSONDecodeError:
                    raise ValueError(_("Unable to parse server response as JSON: {response_text}").format(response_text=result.text))

                self._cached_models, self._all_model_list = self._parse_catalogue(data)

        except Exception as e:
            logging.error(_("Unable to retrieve available models: {error}").format(error=str(e)))
            raise

    def _parse_catalogue(self, data : Any) -> tuple[dict[str, dict[str, str]], list[str]]:
        """
        Group catalogue entries by family as display name -> model ID, and list every model ID.

        Override this for a catalogue the definition cannot describe.
        """
        return self.definition.catalogue.Parse(data, self.name)

    def _get_model_id(self, display_name: str) -> str:
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
