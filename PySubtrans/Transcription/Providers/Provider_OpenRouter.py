import json
import logging
import os

import httpx

from PySubtrans.Helpers.Localization import _
from PySubtrans.Options import env_float
from PySubtrans.SettingsType import GuiSettingsType, SettingsType
from PySubtrans.Transcription.TranscriptionClient import TranscriptionClient
from PySubtrans.Transcription.TranscriptionProvider import OptionsScope, TranscriptionProvider

class OpenRouterTranscriptionProvider(TranscriptionProvider):
    """
    Speech-to-text via OpenRouter with the shared account API key.
    """
    name = "OpenRouter"

    information = _("""
    <p>Transcribe with OpenRouter speech-to-text models.</p>
    <p>Word timestamps and diarization depend on the selected model.</p>
    """)

    information_noapikey = _("""
    <p>To use this provider you need <a href="https://openrouter.ai/keys">an OpenRouter API key</a>.</p>
    """)

    default_transcription_model = 'microsoft/mai-transcribe-2'

    @property
    def supports_diarization(self) -> bool:
        """Speaker labels when diarization is requested on a mapped model."""
        return self.settings.get_bool('diarize', False)

    def __init__(self, settings : SettingsType):
        super().__init__(self.name, settings)
        self.settings = SettingsType(self.settings | {
            'api_key': settings.get_str('api_key', os.getenv('OPENROUTER_API_KEY')),
            'server_address': settings.get_str('server_address', os.getenv('OPENROUTER_SERVER_ADDRESS', 'https://openrouter.ai/api/v1')),
            'model': settings.get_str('model', os.getenv('OPENROUTER_STT_MODEL', 'microsoft/mai-transcribe-2')),
            'diarize': settings.get_bool('diarize', False),
            'request_timeout': settings.get_float('request_timeout', env_float('TRANSCRIPTION_TIMEOUT', 300.0)),
            'rate_limit': settings.get_float('rate_limit', env_float('OPENROUTER_TRANSCRIPTION_RATE_LIMIT')),
            # Short chunks bound base64 request bodies and the blast radius of retries.
            'min_chunk_seconds': settings.get_float('min_chunk_seconds', 30.0),
            'max_chunk_seconds': settings.get_float('max_chunk_seconds', 120.0),
            'proxy': settings.get_str('proxy') or os.getenv('OPENROUTER_PROXY'),
        })

        self.refresh_when_changed = ['api_key', 'language', 'diarize']

    def GetAvailableModels(self) -> list[str]:
        """
        STT models from the catalog (output modality 'transcription').

        STT ids are absent from the default catalog, hence the filter.
        An empty catalog degrades to the static list, never an error.
        """
        try:
            models = self._list_stt_models()
        except Exception as e:
            logging.debug("Unable to list OpenRouter STT models: {}".format(e))
            models = []

        if models:
            return models

        return ["microsoft/mai-transcribe-2", "deepgram/nova-3", "openai/whisper-large-v3-turbo", "x-ai/grok-stt-1.0"]

    def GetTranscriptionClient(self, settings : SettingsType) -> TranscriptionClient:
        """Returns a new client merging provider defaults with call settings."""
        # Sanctioned lazy import: keeps provider registration light.
        from PySubtrans.Transcription.Providers.Clients.OpenRouterTranscriptionClient import OpenRouterTranscriptionClient
        client_settings = SettingsType(self.settings.copy())
        client_settings.update(settings)
        return OpenRouterTranscriptionClient(client_settings)

    def GetOptions(self, settings : SettingsType, scope : OptionsScope = OptionsScope.ALL) -> GuiSettingsType:
        """
        Returns the configurable options for the provider.
        """
        options : GuiSettingsType = {}

        if scope is OptionsScope.ALL:
            options['api_key'] = (str, _("An OpenRouter API key (shared with translation)"))

        if not self.settings.get_str('api_key'):
            return options

        options.update({
            'model': (self.available_models, _("Speech-to-text model")),
            'language': (str, _("Spoken language hint, e.g. Chinese or en (optional, auto-detected when empty)")),
            'diarize': (bool, _("Request speaker diarization (only supported by some models)")),
        })
        options.update(self._chunk_options())

        if scope is OptionsScope.ALL:
            options['request_timeout'] = (float, _("Per-chunk request timeout in seconds"))
            options['rate_limit'] = (float, _("Maximum API requests per minute (0 for unlimited)"))
            options.update(self._line_options())

        return options

    def ResolveLanguageCode(self, language : str|None, display_language : str|None = None) -> str|None:
        """Whisper-compatible endpoints take an ISO 639-1 code ("en", "zh"), or None to auto-detect."""
        locale = self.ResolveLanguageLocale(language, display_language)
        return locale.language if locale is not None else None

    def ValidateSettings(self) -> bool:
        """Validate the settings for the provider."""
        if not self.settings.get_str('api_key'):
            self.validation_message = _("API Key is required")
            return False

        return True

    def _list_stt_models(self) -> list[str]:
        # Never raises: an unreachable or malformed catalog is an expected
        # configuration (offline, bad key), and the static fallback applies.
        # Deliberately exception-free so break-on-any-exception debuggers
        # stay quiet on this routine path.
        address = (self.settings.get_str('server_address') or '').rstrip('/')
        if not address:
            return []

        headers = {}
        api_key = self.settings.get_str('api_key')
        if api_key:
            headers['Authorization'] = f"Bearer {api_key}"

        proxy = self.settings.get_str('proxy')
        try:
            with httpx.Client(timeout=20, proxy=proxy) as client:
                response = client.get(f"{address}/models?output_modalities=transcription", headers=headers)
        except Exception:
            return []

        if response.is_error:
            return []

        # Peek before parsing: error pages come back as HTML, which can
        # never be a model catalog. Anything unexpected degrades quietly.
        text = (response.text or '').strip()
        if not text.startswith(('{', '[')):
            return []

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return []

        if not isinstance(data, dict):
            return []

        ids = [m.get('id', '') for m in data.get('data', [])
               if isinstance(m, dict) and m.get('id')]

        return sorted(set(ids))

