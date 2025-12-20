import importlib.util
import logging
import os

from PySubtrans.Options import SettingsType, env_float, env_int
from PySubtrans.SettingsType import GuiSettingsType, SettingsType

if not importlib.util.find_spec("google"):
    from PySubtrans.Helpers.Localization import _
    logging.debug(_("Google SDK (google-genai) is not installed. Gemini provider will not be available"))
else:
    try:
        from collections import defaultdict

        from google import genai
        from google.genai.types import ListModelsConfig, HttpOptions
        from google.api_core.exceptions import FailedPrecondition

        from PySubtrans.Helpers.Localization import _
        from PySubtrans.Providers.Clients.GeminiClient import GeminiClient
        from PySubtrans.TranslationClient import TranslationClient
        from PySubtrans.TranslationProvider import TranslationProvider

        class GeminiProvider(TranslationProvider):
            name = "Gemini"

            default_model = "gemini-3-flash-preview"

            information = """
            <p>Select the <a href="https://ai.google.dev/models/gemini">AI model</a> to use as a translator.</p>
            <p>Please note that the Gemini API can currently only be accessed from IP addresses in <a href="https://ai.google.dev/available_regions">certain regions</a>.</p>
            <p>You must ensure that the Generative Language API is enabled for your project and/or API key.</p>
            """

            information_noapikey = """
            <p>Please note that the Gemini API can currently only be accessed from IP addresses in <a href="https://ai.google.dev/available_regions">certain regions</a>.</p>
            <p>To use this provider you need to create an API Key <a href="https://aistudio.google.com/app/apikey">Google AI Studio</a>
            or a project on <a href="https://console.cloud.google.com/">Google Cloud Platform</a> and enable Generative Language API access.</p>
            """

            def __init__(self, settings : SettingsType):
                super().__init__(self.name, SettingsType({
                    "api_key": settings.get_str('api_key') or os.getenv('GEMINI_API_KEY'),
                    "model": settings.get_str('model') or os.getenv('GEMINI_MODEL', self.default_model),
                    'stream_responses': settings.get_bool('stream_responses', os.getenv('GEMINI_STREAM_RESPONSES', "True") == "True"),
                    'enable_thinking': settings.get_bool('enable_thinking', os.getenv('GEMINI_ENABLE_THINKING', "False") == "True"),
                    'thinking_budget': settings.get_int('thinking_budget', env_int('GEMINI_THINKING_BUDGET', 100)) or 100,
                    'temperature': settings.get_float('temperature', env_float('GEMINI_TEMPERATURE', 0.0)),
                    'rate_limit': settings.get_float('rate_limit', env_float('GEMINI_RATE_LIMIT', 60.0)),
                    'proxy': settings.get_str('proxy') or os.getenv('GEMINI_PROXY'),
                }))

                self.refresh_when_changed = ['api_key', 'model', 'enable_thinking']
                self.gemini_models = []
                self.excluded_models = ["vision", "tts", "banana"]

            @property
            def api_key(self) -> str|None:
                return self.settings.get_str( 'api_key')

            def GetTranslationClient(self, settings : SettingsType) -> TranslationClient:
                client_settings = SettingsType(self.settings.copy())
                client_settings.update(settings)
                client_settings.update({
                    'model': self._get_true_name(self.selected_model),
                    'supports_streaming': True,
                    'supports_conversation': False,         # Actually it does support conversation
                    'supports_system_messages': False,       # This is what it doesn't support
                    'supports_system_prompt': True
                    })
                return GeminiClient(client_settings)

            def GetOptions(self, settings : SettingsType) -> GuiSettingsType:
                options : GuiSettingsType = {
                    'api_key': (str, _("A Google Gemini API key is required to use this provider (https://makersuite.google.com/app/apikey)"))
                }

                if self.api_key:
                    try:
                        models = self.available_models
                        if models:
                            options.update({
                                'model': (models, "AI model to use as the translator" if models else "Unable to retrieve models"),
                                'stream_responses': (bool, _("Stream translations in realtime as they are generated")),
                                'enable_thinking': (bool, _("Enable reasoning capabilities for more complex translations (increases cost)")),
                                'temperature': (float, _("Amount of random variance to add to translations. Generally speaking, none is best")),
                                'rate_limit': (float, _("Maximum API requests per minute."))
                            })

                            if self.settings.get_bool('enable_thinking', False):
                                options['thinking_budget'] = (int, _("Token budget for reasoning. Higher values increase cost"))

                        else:
                            options['model'] = (["Unable to retrieve models"], _("Check API key is authorized and try again"))

                    except FailedPrecondition as e:
                        options['model'] = (["Unable to access the Gemini API"], str(e))

                return options

            def GetAvailableModels(self) -> list[str]:
                if not self.gemini_models:
                    self.gemini_models = self._get_gemini_models()

                return sorted([m.display_name for m in self.gemini_models])

            def GetInformation(self) -> str:
                return self.information if self.api_key else self.information_noapikey

            def ValidateSettings(self) -> bool:
                """
                Validate the settings for the provider
                """
                if not self.api_key:
                    self.validation_message = _("API Key is required")
                    return False

                if not self.GetAvailableModels():
                    self.validation_message = "Unable to retrieve models. Gemini API may be unavailable in your region."
                    return False

                return True

            def _get_gemini_models(self):
                if not self.api_key:
                    return []

                try:
                    # Respect proxy when listing models too (strongly typed HttpOptions)
                    proxy = self.settings.get_str('proxy')
                    http_options = HttpOptions(api_version='v1beta')
                    if proxy:
                        http_options.client_args = {'proxy': proxy}
                        http_options.async_client_args = {'proxy': proxy}
                        logging.debug(f"Using proxy for Gemini model listing: {proxy}")
                    gemini_client = genai.Client(api_key=self.api_key, http_options=http_options)
                    config = ListModelsConfig(query_base=True)
                    all_models = gemini_client.models.list(config=config)
                    generate_models = [ m for m in all_models if m.supported_actions and 'generateContent' in m.supported_actions ]
                    text_models = [m for m in generate_models if m.display_name and not any(exclusion in m.display_name.lower() for exclusion in self.excluded_models)]

                    return self._deduplicate_models(text_models)

                except Exception as e:
                    logging.error(_("Unable to retrieve Gemini model list: {error}").format(error=str(e)))
                    return []

            def _get_true_name(self, name : str|None) -> str:
                if not self.gemini_models:
                    self.gemini_models = self._get_gemini_models()

                if not name:
                    return self.gemini_models[0].name if self.gemini_models else ""

                for m in self.gemini_models:
                    if m.name == f"models/{name}" or m.display_name == name:
                        return m.name

                raise ValueError(f"Model {name} not found")

            def _deduplicate_models(self, models : list) -> list:
                """Deduplicate models by display name, preferring -latest versions"""
                # Group models by display name
                model_groups = defaultdict(list)
                for model in models:
                    model_groups[model.display_name].append(model)
                
                # Select best model for each display name  
                selected_models = [
                    latest_models[0] if (latest_models := [m for m in models if m.name.endswith('-latest')])
                    else min(models, key=lambda m: len(m.name))
                    for models in model_groups.values()
                ]
                
                return selected_models

            def _allow_multithreaded_translation(self) -> bool:
                """
                If user has set a rate limit don't attempt parallel requests to make sure we respect it
                """
                if self.settings.get_float( 'rate_limit', 0.0) != 0.0:
                    return False

                return True

    except ImportError:
        from PySubtrans.Helpers.Localization import _
        logging.info(_("Latest Google AI SDK (google-genai) is not installed. Gemini provider will not be available. Run installer or `pip install google-genai` to fix."))

