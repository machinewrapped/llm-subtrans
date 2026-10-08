import json
import logging
import os

import httpx

from PySubtrans.Helpers.Localization import _
from PySubtrans.Options import env_float
from PySubtrans.SettingsType import GuiSettingsType, SettingsType
from PySubtrans.Transcription.TranscriptionClient import TranscriptionClient
from PySubtrans.Transcription.TranscriptionProvider import OptionsScope, TranscriptionProvider

# Vendor options are not top-level OpenRouter fields; each vendor takes its own under its provider slug
_DIARIZATION_OPTIONS : dict[str, dict] = {
    'microsoft/': {'azure': {'diarization': {'enabled': True}}},
    'deepgram/': {'deepgram': {'diarize': True}},
    'elevenlabs/': {'elevenlabs': {'diarize': True}},
    'x-ai/': {'xai': {'diarize': True}},
}

# Options sent with every request to the vendor.
# ElevenLabs tags audio events such as [laughter] inline by default, which puts them into subtitle lines.
_REQUEST_OPTIONS : dict[str, dict] = {
    'elevenlabs/': {'elevenlabs': {'tag_audio_events': False}},
}

def DiarizationOptions(model : str) -> dict|None:
    """The provider options that request diarization for *model*, or None if it cannot be diarized."""
    return _MatchModel(_DIARIZATION_OPTIONS, model)

def ProviderOptions(model : str, diarize : bool) -> dict:
    """The provider options to send for *model*, with diarization when requested and supported."""
    sources = [_MatchModel(_REQUEST_OPTIONS, model)]
    if diarize:
        sources.append(DiarizationOptions(model))

    options : dict[str, dict] = {}
    for source in sources:
        for slug, values in (source or {}).items():
            options[slug] = options.get(slug, {}) | values

    return options

def _MatchModel(table : dict[str, dict], model : str) -> dict|None:
    """The entry in *table* whose prefix matches *model*, if any."""
    model_cf = model.casefold()
    for prefix, options in table.items():
        if model_cf.startswith(prefix):
            return options
    return None

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
        """Speaker labels when diarization is enabled and the model can be diarized."""
        return self.settings.get_bool('diarize', True) and self._model_can_diarize

    @property
    def _model_can_diarize(self) -> bool:
        """Whether the selected model has a known diarization option."""
        return DiarizationOptions(self.selected_model or self.default_transcription_model) is not None

    def __init__(self, settings : SettingsType):
        super().__init__(self.name, settings)
        self.settings = SettingsType(self.settings | {
            'api_key': settings.get_str('api_key', os.getenv('OPENROUTER_API_KEY')),
            'server_address': settings.get_str('server_address', os.getenv('OPENROUTER_SERVER_ADDRESS', 'https://openrouter.ai/api/v1')),
            'model': settings.get_str('model', os.getenv('OPENROUTER_STT_MODEL', 'microsoft/mai-transcribe-2')),
            'diarize': settings.get_bool('diarize', True),
            'request_timeout': settings.get_float('request_timeout', env_float('TRANSCRIPTION_TIMEOUT', 300.0)),
            'rate_limit': settings.get_float('rate_limit', env_float('OPENROUTER_TRANSCRIPTION_RATE_LIMIT')),
            # Short chunks bound base64 request bodies and the blast radius of retries.
            'min_chunk_seconds': settings.get_float('min_chunk_seconds', 30.0),
            'max_chunk_seconds': settings.get_float('max_chunk_seconds', 120.0),
            'proxy': settings.get_str('proxy') or os.getenv('OPENROUTER_PROXY'),
        })

        self.refresh_when_changed = ['api_key', 'model', 'language', 'diarize']

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
        })

        if self._model_can_diarize:
            options['diarize'] = (bool, _("Identify speakers"))

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

