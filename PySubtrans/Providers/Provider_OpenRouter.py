import json
import logging
import os
import httpx

from PySubtrans.Helpers.Localization import _
from PySubtrans.Options import SettingsType, env_float, env_int
from PySubtrans.Providers.Clients.OpenRouterClient import OpenRouterClient
from PySubtrans.SettingsType import GuiSettingsType, SettingsType
from PySubtrans.TranslationClient import TranslationClient
from PySubtrans.TranslationProvider import TranslationProvider

class OpenRouterProvider(TranslationProvider):
    name = "OpenRouter"
    
    information = """
    <p>Select the <a href="https://openrouter.ai/models">model</a> to use as a translator.</p>
    <p>OpenRouter provides access to many different AI models from various providers.</p>
    <p>Model selection can be handled automatically by OpenRouter, or you can choose a specific provider and model.</p>
    <p>By default the model list is selected from the `Translation` category, but many other models can do the job.</p>
    """

    information_noapikey = """
    <p>To use this provider you need <a href="https://openrouter.ai/keys">an OpenRouter API key</a>.</p>
    <p>Note that you must have credit to use OpenRouter models.</p>
    """

    def __init__(self, settings : SettingsType):
        super().__init__(self.name, SettingsType({
            'api_key': settings.get_str('api_key', os.getenv('OPENROUTER_API_KEY')),
            'use_default_model': settings.get_bool('use_default_model', False),
            "server_address": settings.get_str('server_address', os.getenv('OPENROUTER_SERVER_ADDRESS', "https://openrouter.ai/api/")),
            'model_family': settings.get_str('model_family', os.getenv('OPENROUTER_MODEL_FAMILY', "Google")),
            'only_translation_models': settings.get_bool('only_translation_models', True),
            "model": settings.get_str('model', os.getenv('OPENROUTER_MODEL', "Gemini 2.5 Flash Lite")),
            'max_tokens': settings.get_int('max_tokens', env_int('OPENROUTER_MAX_TOKENS', 0)),
            'temperature': settings.get_float('temperature', env_float('OPENROUTER_TEMPERATURE', 0.0)),
            'rate_limit': settings.get_float('rate_limit', env_float('OPENROUTER_RATE_LIMIT')),
            'reuse_client': settings.get_bool('reuse_client', True),
        }))

        self.refresh_when_changed = ['api_key', 'model', 'only_translation_models', 'model_family', 'use_default_model']
        self._all_model_list = []
        self._cached_models : dict[str, dict[str,str]] = {}
        self._model_cache_filtered = False

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
        Returns a list of available providers for the OpenRouter API
        """
        available_families = sorted(self._cached_models.keys()) if self._cached_models else []
        valid_families : list[str] = [family for family in available_families if isinstance(family, str)]
        if self.model_family is not None and self.model_family not in valid_families:
            valid_families = [self.model_family] + valid_families
        return valid_families
        
    @property
    def model_family(self) -> str|None:
        return self.settings.get_str( 'model_family', "Google")

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
        Returns a new instance of the OpenRouter client 
        """
        client_settings = SettingsType(self.settings.copy())
        client_settings.update(settings)

        if self.use_default_model:
            # Let OpenRouter decide which model to use
            client_settings['model'] = "openrouter/auto"
        else:
            # Convert display name back to model ID
            model = self.settings.get_str( 'model')
            selected_model = client_settings.get_str('model', default=model)
            if not selected_model:
                selected_model = self.selected_model or "openrouter/auto"
            else:
                client_settings['model'] = self._get_model_id(selected_model)
        
        return OpenRouterClient(client_settings)

    def GetOptions(self, settings : SettingsType) -> GuiSettingsType:
        """
        Returns a dictionary of options for the OpenRouter provider
        """
        options = {
            'api_key': (str, _( "An OpenRouter API key is required to use this provider (https://openrouter.ai/keys)")),
            'use_default_model': (bool, _( "Use the default model and hide advanced model options")),
        }

        if not self.api_key:
            return options

        if not settings.get_bool('use_default_model'):
            # Present model hierarchy if not using default model
            options['only_translation_models'] = (bool, _( "Only show models from the translation category"))

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
            logging.debug("No OpenRouter API key provided")
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
        Fetch and cache models grouped by family from OpenRouter API
        """
        if not self.api_key:
            return
        
        if self._cached_models and self._model_cache_filtered == self.settings.get_bool( 'only_translation_models', True):
            return  # Cache already populated with current filter setting
            
        try:
            # Build URL with translation filter if enabled
            use_model_filter = self.settings.get_bool( 'only_translation_models', True)
            if not self.server_address:
                logging.debug("No OpenRouter server address provided")
                return

            url = self.server_address.rstrip('/') + '/v1/models'
            if use_model_filter:
                url += '?category=translation'

            headers = {'Authorization': f"Bearer {self.api_key}"} if self.api_key else {}

            with httpx.Client(timeout=20) as client:
                result = client.get(url, headers=headers)
                if result.is_error:
                    logging.error(_("Error fetching models: {status} {text}").format(
                        status=result.status_code, text=result.text))
                    return

                try:
                    data = result.json()
                    models_data = data.get('data', [])
                    model_cache = {}

                    # Filter models to only those with 'text' in both input_modalities and output_modalities
                    filtered_models = []
                    for model in models_data:
                        arch = model.get('architecture', {})
                        input_modalities = arch.get('input_modalities', [])
                        output_modalities = arch.get('output_modalities', [])
                        if 'text' in input_modalities and 'text' in output_modalities:
                            filtered_models.append(model)

                    self._all_model_list = sorted(self._get_model_name(model)[1] for model in filtered_models if model.get('name'))

                    # Group models by family based on model name
                    for model in filtered_models:
                        model_id = model.get('id', '')
                        model_series, model_name = self._get_model_name(model)

                        if model_series not in model_cache:
                            model_cache[model_series] = {}

                        # Store display name -> model_id mapping
                        display_name = model_name if model_name else model_id
                        model_cache[model_series][display_name] = model_id

                    self._cached_models = model_cache
                    self._model_cache_filtered = use_model_filter

                except json.JSONDecodeError:
                    logging.error(_("Unable to parse server response as JSON: {response_text}").format(response_text=result.text))
                    return

        except Exception as e:
            logging.error(_("Unable to retrieve available models: {error}").format(error=str(e)))
            return

    def _get_model_name(self, model : dict) -> tuple[str, str]:
        """
        Split model name into series and name
        """
        full_model_name = model.get('name', '')
        model_series, model_name = full_model_name.split(': ', 1) if ': ' in full_model_name else ("Generic", full_model_name)
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