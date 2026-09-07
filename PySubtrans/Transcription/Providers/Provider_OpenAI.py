import os
from datetime import timedelta

from PySubtrans.Helpers.Localization import _
from PySubtrans.Helpers.Parse import TryParseFloat
from PySubtrans.Options import SettingsType, env_float
from PySubtrans.SettingsType import GuiSettingsType, SettingsType
from PySubtrans.Transcription.TranscriptionAligner import WordTiming
from PySubtrans.Transcription.TranscriptionClient import TranscriptionClient
from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionSegment


def _to_seconds(value : object) -> float|None:
    """Non-negative seconds from a payload number, None when absent."""
    parsed = TryParseFloat(value)
    return max(0.0, parsed) if parsed is not None else None


def parse_diarized_payload(payload : dict) -> tuple[str, list[TranscriptionSegment]]:
    """
    Extract (text, parts) from a diarized_json response.

    Pure function over the diarized shape so it is unit-testable without
    network access. Segments carry chunk-relative timings with speaker
    labels (mapped names or A/B/C when no references were given).
    """
    text = str(payload.get('text') or '').strip()

    parts : list[TranscriptionSegment] = []
    for entry in payload.get('segments') or []:
        if not isinstance(entry, dict):
            continue
        entry_text = str(entry.get('text') or '').strip()
        start = _to_seconds(entry.get('start'))
        end = _to_seconds(entry.get('end'))
        if not entry_text or start is None or end is None or end <= start:
            continue
        speaker = entry.get('speaker')
        parts.append(TranscriptionSegment(
            start=timedelta(seconds=start), end=timedelta(seconds=end),
            text=entry_text,
            speaker=str(speaker) if speaker is not None else None))

    return text, parts


def parse_verbose_payload(payload : dict) -> tuple[str, str|None, list[WordTiming]]:
    """
    Extract (text, language, words) from a whisper verbose_json response.
    """
    text = str(payload.get('text') or '').strip()
    language = payload.get('language')
    language = str(language).strip() if language else None

    words : list[WordTiming] = []
    for entry in payload.get('words') or []:
        if not isinstance(entry, dict):
            continue
        word_text = str(entry.get('word') or entry.get('text') or '').strip()
        start = _to_seconds(entry.get('start'))
        end = _to_seconds(entry.get('end'))
        if not word_text or start is None or end is None or end <= start:
            continue
        words.append(WordTiming(text=word_text,
                                start=timedelta(seconds=start),
                                end=timedelta(seconds=end)))

    words.sort(key=lambda w: w.start)
    return text, language, words


class OpenAITranscriptionProvider(TranscriptionProvider):
    """
    Speech-to-text via OpenAI with the shared account API key.

    Only timed models are served: whisper-1 (word timestamps) and
    gpt-4o-transcribe-diarize (speaker segments). The plain gpt-transcribe
    family returns no timings and is refused at validation.
    """
    name = "OpenAI"

    information = _("""
    <p>Transcribe with OpenAI speech-to-text models over one API key.</p>
    <p>Currently experimental and untested due to expired API credits. Please report your experiences!</p>
    """)

    information_noapikey = _("""
    <p>To use this provider you need <a href="https://platform.openai.com/account/api-keys">an OpenAI API key</a>.</p>
    """)

    # Endpoint and quotas live in Settings; model and language vary per job
    advanced_settings = ['api_key', 'request_timeout', 'rate_limit']

    @property
    def recommended_min_chunk_seconds(self) -> float:
        """Short chunks bound request bodies and the blast radius of retries."""
        return 8.0

    @property
    def recommended_max_chunk_seconds(self) -> float:
        """Short chunks bound request bodies and the blast radius of retries."""
        return 60.0

    def __init__(self, settings : SettingsType):
        super().__init__(self.name, SettingsType({
            'api_key': settings.get_str('api_key', os.getenv('OPENAI_API_KEY')),
            'server_address': settings.get_str('server_address', os.getenv('OPENAI_SERVER_ADDRESS', 'https://api.openai.com/v1')),
            'model': settings.get_str('model', os.getenv('OPENAI_STT_MODEL', 'whisper-1')),
            'language': settings.get_str('language', os.getenv('TRANSCRIPTION_LANGUAGE')),
            'request_timeout': settings.get_float('request_timeout', env_float('TRANSCRIPTION_TIMEOUT', 300.0)),
            'rate_limit': settings.get_float('rate_limit', env_float('OPENAI_TRANSCRIPTION_RATE_LIMIT')),
            'proxy': settings.get_str('proxy') or os.getenv('OPENAI_PROXY'),
        }))

        self.refresh_when_changed = ['api_key']

    def GetAvailableModels(self) -> list[str]:
        """Timed transcription models served by this provider."""
        return ['whisper-1', 'gpt-4o-transcribe-diarize']

    def GetTranscriptionClient(self, settings : SettingsType) -> TranscriptionClient:
        """Returns a new client merging provider defaults with call settings."""
        # Sanctioned lazy import: keeps provider registration light.
        from PySubtrans.Transcription.Providers.Clients.OpenAITranscriptionClient import OpenAITranscriptionClient
        client_settings = SettingsType(self.settings.copy())
        client_settings.update(settings)
        return OpenAITranscriptionClient(client_settings)

    def GetOptions(self, settings : SettingsType) -> GuiSettingsType:
        """
        Returns the configurable options for the provider.
        """
        options : GuiSettingsType = {
            'api_key': (str, _("An OpenAI API key (shared with translation)")),
        }
        if not self.settings.get_str('api_key'):
            return options
        options.update({
            'model': (self.available_models, _("Speech-to-text model (both return timings)")),
            'language': (str, _("Spoken language hint as ISO code, e.g. en (optional)")),
            'request_timeout': (float, _("Per-chunk request timeout in seconds")),
            'rate_limit': (float, _("Maximum API requests per minute (0 for unlimited)")),
        })
        return options

    def ValidateSettings(self) -> bool:
        """Validate the settings for the provider."""
        if not self.settings.get_str('api_key'):
            self.validation_message = _("API Key is required")
            return False

        model = (self.settings.get_str('model') or '').strip().casefold()
        if model in ('gpt-transcribe', 'gpt-4o-transcribe', 'gpt-4o-mini-transcribe'):
            self.validation_message = _("Model '{}' returns no timings and cannot produce subtitles").format(
                self.settings.get_str('model'))
            return False

        return True
