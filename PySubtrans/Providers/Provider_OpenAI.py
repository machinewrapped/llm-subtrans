import importlib.util
import logging
import os

from PySubtrans.Options import SettingsType, env_bool, env_float
from PySubtrans.SettingsType import GuiSettingsType, SettingsType

# Minimum seconds an access token must remain valid when a ChatGPT plan client is created
CLIENT_TOKEN_VALIDITY = 1800.0

if not importlib.util.find_spec("openai"):
    from PySubtrans.Helpers.Localization import _
    logging.debug(_("OpenAI SDK is not installed. OpenAI provider will not be available"))
else:
    try:
        from PySubtrans.Auth.ChatGPTAuth import API_RESOURCE, MANAGE_USAGE_URL, ChatGPTAuth, ChatGPTAuthError, ChatGPTSignInOption, ChatGPTSignOutOption
        from PySubtrans.Helpers.Localization import _
        from PySubtrans.SubtitleError import ProviderError
        from PySubtrans.TranslationClient import TranslationClient
        from PySubtrans.TranslationProvider import TranslationProvider

        class OpenAiProvider(TranslationProvider):
            name = "OpenAI"

            default_model = "gpt-6-luna"

            information = """
            <p>Select the AI <a href="https://platform.openai.com/docs/models">model</a> to use as a translator.</p>
            <p>Note that different models have different <a href="https://openai.com/pricing">costs</a> and limitations.</p>
            """

            information_instructmodels = "<p>Instruct models require the maximum output tokens to be specified. This should be roughly half the maximum tokens the model supports.</p>"

            information_noapikey = """
            <p>To use this provider you need <a href="https://platform.openai.com/account/api-keys">an OpenAI API key</a>.</p>
            <p>Api Base can usually be left blank unless you are using a custom OpenAI instance, when you will need to provide the base URL.</p>
            <p>Note that if your API Key is attached to a free trial account the <a href="https://platform.openai.com/docs/guides/rate-limits?context=tier-free">rate limit</a> for requests will be <i>severely</i> limited.</p>
            <p>If you have a ChatGPT plan, you can select Use ChatGPT plan to sign in with ChatGPT instead of using an API key.</p>
            """

            information_chatgpt = f"""
            <p>Using ChatGPT plan.</p>
            <p>Translation requests use the usage allowance of your ChatGPT plan instead of an API key, subject to your plan's limits.
            You can <a href="{MANAGE_USAGE_URL}">manage usage</a> in your ChatGPT settings.</p>
            <p>Select the AI <a href="https://platform.openai.com/docs/models">model</a> to use as a translator. The models available depend on your plan.</p>
            <p>Your ChatGPT plan can only be used for translation. Transcription with OpenAI still needs an API key.</p>
            """

            information_chatgpt_signin = """
            <p>Sign in with ChatGPT to translate using the usage allowance of your ChatGPT plan, instead of a separately billed API key.</p>
            <p>Sign-in opens in your web browser.</p>
            """

            def __init__(self, settings : SettingsType):
                super().__init__(self.name, SettingsType({
                    "use_chatgpt_plan": settings.get_bool('use_chatgpt_plan', env_bool('OPENAI_USE_CHATGPT_PLAN')),
                    "chatgpt_account": settings.get_str('chatgpt_account'),
                    "api_key": settings.get_str('api_key', os.getenv('OPENAI_API_KEY')),
                    "api_base": settings.get_str('api_base', os.getenv('OPENAI_API_BASE')),
                    "model": settings.get_str('model', os.getenv('OPENAI_MODEL', self.default_model)),
                    'temperature': settings.get_float('temperature', env_float('OPENAI_TEMPERATURE', 0.0)),
                    'rate_limit': settings.get_float('rate_limit', env_float('OPENAI_RATE_LIMIT')),
                    "free_plan": settings.get_bool('free_plan', os.getenv('OPENAI_FREE_PLAN') == "True"),
                    'max_instruct_tokens': settings.get_int('max_instruct_tokens', int(os.getenv('MAX_INSTRUCT_TOKENS', '2048'))),
                    'use_httpx': settings.get_bool('use_httpx', os.getenv('OPENAI_USE_HTTPX', "False") == "True"),
                    'reasoning_effort': settings.get_str('reasoning_effort', os.getenv('OPENAI_REASONING_EFFORT', "low")),
                    'stream_responses': settings.get_bool('stream_responses', os.getenv('OPENAI_STREAM_RESPONSES', "False") == "True"),
                    'proxy': settings.get_str('proxy') or os.getenv('OPENAI_PROXY'),
                }))

                self.refresh_when_changed = ['use_chatgpt_plan', 'chatgpt_account', 'api_key', 'api_base', 'model']

                self.valid_model_types = [ "gpt", "o1", "o3", "o4" ]
                self.excluded_model_types = [ "vision", "image", "realtime", "audio", "instruct", "search", "transcribe", "tts", "deep-research", "codex" ]
                self.non_reasoning_models = [ "gpt-3", "gpt-4", "gpt-5-chat" ]

            @property
            def api_key(self) -> str|None:
                return self.settings.get_str( 'api_key')

            @property
            def api_base(self) -> str|None:
                return self.settings.get_str( 'api_base')

            @property
            def uses_chatgpt_plan(self) -> bool:
                return self.settings.get_bool('use_chatgpt_plan')

            @property
            def chatgpt_auth(self) -> ChatGPTAuth:
                return ChatGPTAuth(proxy=self.settings.get_str('proxy'))

            @property
            def is_instruct_model(self) -> bool:
                return self.selected_model is not None and self.model_is_instruct_model(self.selected_model)

            @property
            def is_reasoning_model(self) -> bool:
                return self.selected_model is not None and self.model_is_reasoning_model(self.selected_model)

            def model_is_instruct_model(self, model_name : str) -> bool:
                return model_name.find("instruct") >= 0

            def model_is_reasoning_model(self, model_name : str) -> bool:
                return not any(model_name.startswith(model) for model in self.non_reasoning_models)

            def GetTranslationClient(self, settings : SettingsType) -> TranslationClient:
                client_settings = SettingsType(self.settings.copy())
                client_settings.update(settings)
                if self.uses_chatgpt_plan:
                    # Sanctioned lazy import: defer the measured 2.4-second OpenAI SDK load until reasoning translation is selected.
                    from PySubtrans.Providers.Clients.OpenAIReasoningClient import OpenAIReasoningClient

                    # The client keeps this token, so make sure it has a reasonable time left to run
                    try:
                        access_token = self.chatgpt_auth.GetAccessToken(min_validity=CLIENT_TOKEN_VALIDITY)
                    except ChatGPTAuthError as e:
                        raise ProviderError(str(e), provider=self) from e

                    # ChatGPT plan usage requires the public API, with every response streamed and not stored
                    client_settings.update({
                        'api_key': access_token,
                        'api_base': API_RESOURCE,
                        'use_httpx': False,
                        'require_streaming': True,
                        'store_responses': False,
                    })
                    return OpenAIReasoningClient(client_settings)
                elif self.is_instruct_model:
                    raise ProviderError("Instruct models are no longer supported", provider=self)
                elif self.is_reasoning_model:
                    # Sanctioned lazy import: defer the measured 2.4-second OpenAI SDK load until reasoning translation is selected.
                    from PySubtrans.Providers.Clients.OpenAIReasoningClient import OpenAIReasoningClient

                    return OpenAIReasoningClient(client_settings)
                else:
                    # Sanctioned lazy import: defer the measured 2.4-second OpenAI SDK load until chat translation is selected.
                    from PySubtrans.Providers.Clients.ChatGPTClient import ChatGPTClient

                    return ChatGPTClient(client_settings)

            def GetCombinedSettings(self, overrides : SettingsType) -> SettingsType:
                """
                Show the account from the stored ChatGPT sign-in, which may have changed outside the settings
                """
                combined_settings = super().GetCombinedSettings(overrides)
                if self.uses_chatgpt_plan:
                    combined_settings['chatgpt_account'] = self.chatgpt_auth.account or ''
                return combined_settings

            def GetOptions(self, settings : SettingsType) -> GuiSettingsType:
                auth_options : GuiSettingsType = {
                    'use_chatgpt_plan': (bool, _("Sign in with ChatGPT to translate using your ChatGPT plan, instead of an OpenAI API key")),
                }

                if self.uses_chatgpt_plan:
                    return auth_options | self._get_chatgpt_options()

                options : GuiSettingsType = auth_options | {
                    'api_key': (str, _("An OpenAI API key is required to use this provider (https://platform.openai.com/account/api-keys)")),
                    'api_base': (str, _("The base URL to use for requests - leave as default unless you know you need something else")),
                }

                if self.api_base:
                    options['use_httpx'] = (bool, _("Use the httpx library for requests. May help if you receive a 307 redirect error with a custom api_base"))

                if self.api_key:
                    models = self.model_list.known
                    if models:
                        options.update({
                            'model': (models, _("AI model to use as the translator") if models else _("Unable to retrieve models")),
                            'rate_limit': (float, _("Maximum OpenAI API requests per minute. Mainly useful if you are on the restricted free plan"))
                        })

                        model = settings.get_str('model') or self.selected_model or "gpt-5-mini"
                        if self.model_is_instruct_model(model):
                            options['max_instruct_tokens'] = (int, _("Maximum tokens a completion can contain (only applicable for -instruct models)"))

                        if self.model_is_reasoning_model(model):
                            options['reasoning_effort'] = (["none", "minimal", "low", "medium", "high"], _("The level of reasoning effort to use for the model (valid options are model-dependent)"))
                            options['stream_responses'] = (bool, _("Stream translations in realtime as they are generated"))
                        else:
                            options['temperature'] = (float, _("Amount of random variance to add to translations. Generally speaking, none is best"))

                    else:
                        options['model'] = ([_("Unable to retrieve models")], _("Check API key and base URL and try again"))

                return options

            def _get_chatgpt_options(self) -> GuiSettingsType:
                """
                Options for translating with the user's ChatGPT plan
                """
                if not self.chatgpt_auth.is_signed_in:
                    return { 'chatgpt_account': (ChatGPTSignInOption, _("Sign in with ChatGPT to translate using your ChatGPT plan")) }

                options : GuiSettingsType = {
                    'chatgpt_account': (ChatGPTSignOutOption, _("The ChatGPT account whose plan is used for translation")),
                }

                models = self.model_list.known
                if not models:
                    options['model'] = ([_("Unable to retrieve models")], _("Sign out and sign in with ChatGPT again"))
                    return options

                options['model'] = (models, _("AI model to use as the translator"))
                options['reasoning_effort'] = (["none", "minimal", "low", "medium", "high"], _("The level of reasoning effort to use for the model (valid options are model-dependent)"))
                options['stream_responses'] = (bool, _("Stream translations in realtime as they are generated"))
                return options

            @classmethod
            def WarmUp(cls) -> None:
                """Load OpenAI dependencies before the provider is selected in the settings dialog."""
                # Sanctioned background warm-up: preloads the OpenAI SDK that previously cost about 2.4 seconds on first use.
                import openai   # type: ignore
                # Sanctioned background warm-up: preloads the resources package that client.models.list() lazily imports (measured at several seconds on the GUI thread when the settings dialog first opens).
                import openai.resources   # type: ignore
                # Sanctioned background warm-up: preloads the OpenAI chat client path that shares the measured 2.4-second SDK cost.
                from PySubtrans.Providers.Clients.ChatGPTClient import ChatGPTClient
                # Sanctioned background warm-up: preloads the OpenAI reasoning client path that shares the measured 2.4-second SDK cost.
                from PySubtrans.Providers.Clients.OpenAIReasoningClient import OpenAIReasoningClient
                _warmup_imports = (ChatGPTClient, OpenAIReasoningClient, openai.resources)
                del _warmup_imports

            def GetAvailableModels(self) -> list[str]:
                """
                Returns a list of possible values for the LLM model
                """
                if self.uses_chatgpt_plan:
                    return self._get_chatgpt_models()

                try:
                    if not self.api_key:
                        logging.debug("No OpenAI API key provided")
                        return []

                    # Sanctioned lazy import: defer the measured 2.4-second OpenAI SDK load until model listing is requested.
                    import openai   # type: ignore

                    if not hasattr(openai, "OpenAI"):
                        raise ProviderError("The OpenAI library is out of date and must be updated", provider=self)

                    proxy_url = self.settings.get_str('proxy')
                    http_client = openai.DefaultHttpxClient(proxy=proxy_url) if proxy_url else None
                    client = openai.OpenAI(
                        api_key=self.api_key,
                        base_url=self.api_base or None,
                        http_client=http_client
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
                    raise

            def _get_chatgpt_models(self) -> list[str]:
                """
                Returns the models available with the signed-in ChatGPT plan
                """
                auth = self.chatgpt_auth
                if not auth.is_signed_in:
                    logging.debug("Not signed in with ChatGPT")
                    return []

                try:
                    return auth.ListModels()

                except ChatGPTAuthError as e:
                    logging.error(_("Unable to retrieve available AI models: {error}").format(error=str(e)))
                    raise

            def GetInformation(self) -> str:
                if self.uses_chatgpt_plan:
                    return self.information_chatgpt if self.chatgpt_auth.is_signed_in else self.information_chatgpt_signin
                if not self.api_key:
                    return self.information_noapikey
                if self.is_instruct_model:
                    return self.information + self.information_instructmodels
                return self.information

            def ValidateSettings(self) -> bool:
                """
                Validate the settings for the provider
                """
                if self.uses_chatgpt_plan:
                    if not self.chatgpt_auth.is_signed_in:
                        self.validation_message = _("Sign in with ChatGPT is required")
                        return False
                    return True

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
        from PySubtrans.Helpers.Localization import _
        logging.info(_("Failed to initialise OpenAI SDK. OpenAI provider will not be available"))
