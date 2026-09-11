import json
import logging
import os
from datetime import timedelta

import httpx

from PySubtrans.Helpers.Localization import _
from PySubtrans.Helpers.Parse import TryParseNonNegative
from PySubtrans.Options import env_float
from PySubtrans.SettingsType import GuiSettingsType, SettingsType
from PySubtrans.Transcription.TranscriptionAligner import WordTiming
from PySubtrans.Transcription.TranscriptionClient import TranscriptionClient
from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionSegment


def parse_transcription_payload(payload : dict) -> tuple[str, str|None, list[TranscriptionSegment], list[WordTiming]]:
    """
    Extract (text, language, parts, words) from an OpenRouter STT response.

    Pure function over the verbose_json shape so it is unit-testable
    without network access. Segments and words carry chunk-relative
    timings; speaker labels pass through untouched when present.
    Duration and usage cost attach to the result built by the caller
    (see _attach_usage).
    """
    text = str(payload.get('text') or '').strip()
    language = payload.get('language')
    language = str(language).strip() if language else None

    parts : list[TranscriptionSegment] = []
    for entry in payload.get('segments') or []:
        if not isinstance(entry, dict):
            continue
        entry_text = str(entry.get('text') or '').strip()
        start = TryParseNonNegative(entry.get('start'))
        end = TryParseNonNegative(entry.get('end'))
        if not entry_text or start is None or end is None or end <= start:
            continue
        speaker = entry.get('speaker')
        no_speech_prob = TryParseNonNegative(entry.get('no_speech_prob'))
        parts.append(TranscriptionSegment(
            start=timedelta(seconds=start), end=timedelta(seconds=end),
            text=entry_text,
            speaker=str(speaker) if speaker is not None else None,
            confidence=(1.0 - min(1.0, no_speech_prob)) if no_speech_prob is not None else None))

    words : list[WordTiming] = []
    for entry in payload.get('words') or []:
        if not isinstance(entry, dict):
            continue
        word_text = str(entry.get('word') or entry.get('text') or '').strip()
        start = TryParseNonNegative(entry.get('start'))
        end = TryParseNonNegative(entry.get('end'))
        if not word_text or start is None or end is None or end <= start:
            continue
        speaker = entry.get('speaker')
        words.append(WordTiming(text=word_text,
                                start=timedelta(seconds=start),
                                end=timedelta(seconds=end),
                                speaker=str(speaker) if speaker is not None else None))

    words.sort(key=lambda w: w.start)
    return text, language, parts, words


class OpenRouterTranscriptionProvider(TranscriptionProvider):
    """
    Speech-to-text via OpenRouter with the shared account API key.
    """
    name = "OpenRouter"

    information = _("""
    <p>Transcribe with OpenRouter speech-to-text models.</p>
    <p>Word timestamps and diarization depend on the selected model.</p>
    <p>You must have credit to use OpenRouter models.</p>
    """)

    information_noapikey = _("""
    <p>To use this provider you need <a href="https://openrouter.ai/keys">an OpenRouter API key</a>.</p>
    """)

    # Endpoint and quotas live in Settings; model, diarization and language vary per job
    advanced_settings = ['api_key', 'request_timeout', 'rate_limit']

    @property
    def recommended_min_chunk_seconds(self) -> float:
        """Short chunks bound base64 request bodies and the blast radius of retries."""
        return 8.0

    @property
    def recommended_max_chunk_seconds(self) -> float:
        """Short chunks bound base64 request bodies and the blast radius of retries."""
        return 60.0

    def __init__(self, settings : SettingsType):
        super().__init__(self.name, SettingsType({
            'api_key': settings.get_str('api_key', os.getenv('OPENROUTER_API_KEY')),
            'server_address': settings.get_str('server_address', os.getenv('OPENROUTER_SERVER_ADDRESS', 'https://openrouter.ai/api/v1')),
            'model': settings.get_str('model', os.getenv('OPENROUTER_STT_MODEL', 'openai/whisper-large-v3')),
            'language': settings.get_str('language', os.getenv('TRANSCRIPTION_LANGUAGE')),
            'diarize': settings.get_bool('diarize', False),
            'request_timeout': settings.get_float('request_timeout', env_float('TRANSCRIPTION_TIMEOUT', 300.0)),
            'rate_limit': settings.get_float('rate_limit', env_float('OPENROUTER_TRANSCRIPTION_RATE_LIMIT')),
            'proxy': settings.get_str('proxy') or os.getenv('OPENROUTER_PROXY'),
        }))

        self.refresh_when_changed = ['api_key']

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

        return ['openai/whisper-large-v3', 'openai/whisper-large-v3-turbo',
                'qwen/qwen3-asr-1.7b', 'qwen/qwen3-asr-0.6b',
                'microsoft/mai-transcribe-2', 'google/chirp-3',
                'x-ai/grok-stt-1.0']

    def GetTranscriptionClient(self, settings : SettingsType) -> TranscriptionClient:
        """Returns a new client merging provider defaults with call settings."""
        # Sanctioned lazy import: keeps provider registration light.
        from PySubtrans.Transcription.Providers.Clients.OpenRouterTranscriptionClient import OpenRouterTranscriptionClient
        client_settings = SettingsType(self.settings.copy())
        client_settings.update(settings)
        return OpenRouterTranscriptionClient(client_settings)

    def GetOptions(self, settings : SettingsType) -> GuiSettingsType:
        """
        Returns the configurable options for the provider.
        """
        options : GuiSettingsType = {
            'api_key': (str, _("An OpenRouter API key (shared with translation)")),
        }
        if not self.settings.get_str('api_key'):
            return options
        options.update({
            'model': (self.available_models, _("Speech-to-text model")),
            'language': (str, _("Spoken language hint, e.g. Chinese or en (optional, auto-detected when empty)")),
            'diarize': (bool, _("Request speaker diarization (only supported by some models)")),
            'request_timeout': (float, _("Per-chunk request timeout in seconds")),
            'rate_limit': (float, _("Maximum API requests per minute (0 for unlimited)")),
        })
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
