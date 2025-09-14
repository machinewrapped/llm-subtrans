import importlib.util
import logging
import os

from PySubtitle.Options import SettingsType, env_float
from PySubtitle.SettingsType import GuiSettingsType, SettingsType

if not importlib.util.find_spec("openai"):
    from PySubtitle.Helpers.Localization import _
    logging.info(_("OpenAI SDK is not installed. OpenAI provider will not be available"))
else:
    try:
        import openai   # type: ignore

        from PySubtitle.Helpers.Localization import _
        from PySubtitle.Providers.OpenAI.ChatGPTClient import ChatGPTClient
        from PySubtitle.Providers.OpenAI.OpenAIReasoningClient import OpenAIReasoningClient
        from PySubtitle.SubtitleError import ProviderError
        from PySubtitle.TranslationClient import TranslationClient
        from PySubtitle.TranslationProvider import TranslationProvider

        class OpenAiProvider(TranslationProvider):
            name = "OpenAI"

            information = """
            <p>Select the AI <a href="https://platform.openai.com/docs/models">model</a> to use as a translator.</p>
            <p>Note that different models have different <a href="https://openai.com/pricing">costs</a> and limitations.</p>
            In particular, the number of tokens supported by each model will affect the batch size that it can handle.
            This will depend on the contents but as a rule of thumb 16K token models can handle 80-100 lines per batch.</p>
            <p>GPT4 models are substantially more expensive but are better at following instructions,
            e.g. using provided names, and may be better for more complex translations and less common languages.</p>
            """

            information_instructmodels = "<p>Instruct models require the maximum output tokens to be specified. This should be roughly half the maximum tokens the model supports.</p>"

            information_noapikey = """
            <p>To use this provider you need <a href="https://platform.openai.com/account/api-keys">an OpenAI API key</a>.</p>
            <p>Api Base can usually be left blank unless you are using a custom OpenAI instance, when you will need to provide the base URL.</p>
            <p>Note that if your API Key is attached to a free trial account the <a href="https://platform.openai.com/docs/guides/rate-limits?context=tier-free">rate limit</a> for requests will be <i>severely</i> limited.</p>
            """

            def __init__(self, settings : SettingsType):
                super().__init__(self.name, SettingsType({
                    "api_key": settings.get_str('api_key', os.getenv('OPENAI_API_KEY')),
                    "api_base": settings.get_str('api_base', os.getenv('OPENAI_API_BASE')),
                    "model": settings.get_str('model', os.getenv('OPENAI_MODEL', "gpt-5-mini")),
                    'temperature': settings.get_float('temperature', env_float('OPENAI_TEMPERATURE', 0.0)),
                    'rate_limit': settings.get_float('rate_limit', env_float('OPENAI_RATE_LIMIT')),
                    "free_plan": settings.get_bool('free_plan', os.getenv('OPENAI_FREE_PLAN') == "True"),
                    'max_instruct_tokens': settings.get_int('max_instruct_tokens', int(os.getenv('MAX_INSTRUCT_TOKENS', '2048'))),
                    'use_httpx': settings.get_bool('use_httpx', os.getenv('OPENAI_USE_HTTPX', "False") == "True"),
                    'reasoning_effort': settings.get_str('reasoning_effort', os.getenv('OPENAI_REASONING_EFFORT', "low")),
                }))

                self.refresh_when_changed = ['api_key', 'api_base', 'model']

                self.valid_model_types = [ "gpt", "o1", "o3", "o4" ]
                self.excluded_model_types = [ "vision", "realtime", "audio", "instruct" ]
                self.non_reasoning_models = [ "gpt-3", "gpt-4", "gpt-5-chat" ]

            @property
            def api_key(self) -> str|None:
                return self.settings.get_str( 'api_key')

            @property
            def api_base(self) -> str|None:
                return self.settings.get_str( 'api_base')

            @property
            def is_instruct_model(self) -> bool:
                return self.selected_model is not None and self.selected_model.find("instruct") >= 0

            @property
            def is_reasoning_model(self) -> bool:
                return self.selected_model is not None and not any(self.selected_model.startswith(model) for model in self.non_reasoning_models)

            def GetTranslationClient(self, settings : SettingsType) -> TranslationClient:
                client_settings = SettingsType(self.settings.copy())
                client_settings.update(settings)
                if self.is_instruct_model:
                    raise ProviderError("Instruct models are no longer supported", provider=self)
                elif self.is_reasoning_model:
                    return OpenAIReasoningClient(client_settings)
                else:
                    return ChatGPTClient(client_settings)

            def GetOptions(self, settings : SettingsType) -> GuiSettingsType:
                options : GuiSettingsType = {
                    'api_key': (str, _("An OpenAI API key is required to use this provider (https://platform.openai.com/account/api-keys)")),
                    'api_base': (str, _("The base URL to use for requests - leave as default unless you know you need something else")),
                }

                if self.api_base:
                    options['use_httpx'] = (bool, _("Use the httpx library for requests. May help if you receive a 307 redirect error with a custom api_base"))

                if self.api_key:
                    models = self.available_models
                    if models:
                        options.update({
                            'model': (models, _("AI model to use as the translator") if models else _("Unable to retrieve models")),
                            'rate_limit': (float, _("Maximum OpenAI API requests per minute. Mainly useful if you are on the restricted free plan"))
                        })

                        if self.is_instruct_model:
                            options['max_instruct_tokens'] = (int, _("Maximum tokens a completion can contain (only applicable for -instruct models)"))

                        if self.is_reasoning_model:
                            options['reasoning_effort'] = (["minimal", "low", "medium", "high"], _("The level of reasoning effort to use for the model"))
                        else:
                            options['temperature'] = (float, _("Amount of random variance to add to translations. Generally speaking, none is best"))

                    else:
                        options['model'] = ([_("Unable to retrieve models")], _("Check API key and base URL and try again"))

                return options

            def GetAvailableModels(self) -> list[str]:
                """
                Returns a list of possible values for the LLM model
                """
                try:
                    if not hasattr(openai, "OpenAI"):
                        raise ProviderError("The OpenAI library is out of date and must be updated", provider=self)

                    if not self.api_key:
                        logging.debug("No OpenAI API key provided")
                        return []

                    client = openai.OpenAI(
                        api_key=self.api_key,
                        base_url=self.api_base or None
                    )
                    response = client.models.list()

                    if not response or not response.data:
                        return []

                    model_list = [ model.id for model in response.data if any(model.id.startswith(prefix) for prefix in self.valid_model_types) ]

                    model_list = [ model for model in model_list if not any([ model.find(exclude) >= 0 for exclude in self.excluded_model_types ]) ]

                    # Maybe this isn't really an OpenAI endpoint, just return all the available models
                    if not model_list:
                        model_list = [ model.id for model in response.data ]

                    return sorted(model_list)

                except Exception as e:
                    logging.error(_("Unable to retrieve available AI models: {error}").format(error=str(e)))
                    return []

            def GetInformation(self) -> str:
                if not self.api_key:
                    return self.information_noapikey
                if self.is_instruct_model:
                    return self.information + self.information_instructmodels
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
                If user is on the free plan or has set a rate limit it is better not to try parallel requests
                """
                if self.settings.get_bool( 'free_plan'):
                    return False

                if self.settings.get_float( 'rate_limit', 0.0) != 0.0:
                    return False

                return True

    except ImportError:
        from PySubtitle.Helpers.Localization import _
        logging.info(_("Failed to initialise OpenAI SDK. OpenAI provider will not be available"))