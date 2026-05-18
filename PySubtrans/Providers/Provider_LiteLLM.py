import importlib.util
import logging
import os

from PySubtrans.Helpers.Localization import _
from PySubtrans.Options import env_float, env_int
from PySubtrans.SettingsType import GuiSettingsType, SettingsType

if not importlib.util.find_spec("litellm"):
    logging.debug(_("LiteLLM is not installed. LiteLLM provider will not be available"))
else:
    try:
        from PySubtrans.Providers.Clients.LiteLLMClient import LiteLLMClient
        from PySubtrans.TranslationClient import TranslationClient
        from PySubtrans.TranslationProvider import TranslationProvider

        class LiteLLMProvider(TranslationProvider):
            name = "LiteLLM"

            default_model = "openai/gpt-4o"

            information = """
            <p>LiteLLM provides a unified gateway to 100+ LLM providers.</p>
            <p>Use provider-prefixed model names to route to any provider:</p>
            <ul>
                <li><b>anthropic/claude-sonnet-4-6</b> — Anthropic Claude</li>
                <li><b>openai/gpt-4o</b> — OpenAI</li>
                <li><b>gemini/gemini-2.5-flash</b> — Google Gemini</li>
                <li><b>bedrock/anthropic.claude-v2</b> — AWS Bedrock</li>
            </ul>
            <p>API keys are read from provider-specific env vars (OPENAI_API_KEY, ANTHROPIC_API_KEY, etc.)
            or can be set explicitly in the API Key field.</p>
            <p>Install with: <code>pip install litellm</code></p>
            """

            def __init__(self, settings : SettingsType):
                super().__init__(self.name, SettingsType({
                    'api_key': settings.get_str('api_key', os.getenv('LITELLM_API_KEY')),
                    'api_base': settings.get_str('api_base', os.getenv('LITELLM_API_BASE')),
                    'model': settings.get_str('model', os.getenv('LITELLM_MODEL', self.default_model)),
                    'max_tokens': settings.get_int('max_tokens', env_int('LITELLM_MAX_TOKENS', 0)),
                    'temperature': settings.get_float('temperature', env_float('LITELLM_TEMPERATURE', 0.0)),
                    'rate_limit': settings.get_float('rate_limit', env_float('LITELLM_RATE_LIMIT')),
                }))

                self.refresh_when_changed = ['api_key', 'api_base', 'model']

            @property
            def api_key(self) -> str|None:
                return self.settings.get_str('api_key')

            @property
            def api_base(self) -> str|None:
                return self.settings.get_str('api_base')

            def GetTranslationClient(self, settings : SettingsType) -> TranslationClient:
                """
                Returns a new instance of the LiteLLM client
                """
                client_settings = SettingsType(self.settings.copy())
                client_settings.update(settings)
                client_settings.update({
                    'supports_conversation': True,
                    'supports_system_message': True,
                    'supports_system_messages': True,
                })
                return LiteLLMClient(client_settings)

            def GetOptions(self, settings : SettingsType) -> GuiSettingsType:
                """
                Returns the configurable options for the provider
                """
                options : GuiSettingsType = {
                    'api_key': (str, _("API key (optional — LiteLLM reads provider env vars like OPENAI_API_KEY, ANTHROPIC_API_KEY automatically)")),
                    'api_base': (str, _("Custom API base URL (optional — only needed for self-hosted LiteLLM proxy)")),
                    'model': (str, _("Provider-prefixed model name (e.g. anthropic/claude-sonnet-4-6, openai/gpt-4o, gemini/gemini-2.5-flash)")),
                    'max_tokens': (int, _("Maximum number of output tokens to return in the response")),
                    'temperature': (float, _("Amount of random variance to add to translations")),
                    'rate_limit': (float, _("Maximum API requests per minute")),
                }
                return options

            def GetAvailableModels(self) -> list[str]:
                """
                Returns a list of suggested models for LiteLLM
                """
                return [
                    "openai/gpt-4o",
                    "openai/gpt-4o-mini",
                    "anthropic/claude-sonnet-4-6",
                    "anthropic/claude-haiku-4-5",
                    "gemini/gemini-2.5-flash",
                    "gemini/gemini-2.5-pro",
                    "deepseek/deepseek-chat",
                    "groq/llama-3.3-70b-versatile",
                    "mistral/mistral-large-latest",
                ]

            def GetInformation(self) -> str:
                return self.information

            def _allow_multithreaded_translation(self) -> bool:
                rate_limit = self.settings.get_float('rate_limit')
                if rate_limit is not None and rate_limit != 0.0:
                    return False
                return True

    except ImportError:
        logging.debug(_("Failed to import LiteLLM provider components. LiteLLM provider will not be available"))
