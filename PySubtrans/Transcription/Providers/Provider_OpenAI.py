import os

from PySubtrans.Helpers.Localization import _
from PySubtrans.Options import env_float
from PySubtrans.SettingsType import GuiSettingsType, SettingsType
from PySubtrans.Transcription.TranscriptionClient import TranscriptionClient
from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider


class OpenAITranscriptionProvider(TranscriptionProvider):
    """
    Speech-to-text via OpenAI with the shared account API key.

    Only timed models are served: whisper-1 (word timestamps) and
    gpt-4o-transcribe-diarize (speaker segments). The plain gpt-transcribe
    family returns no timings and is refused at validation.
    """
    name = "OpenAI"

    information = _("""
    <p>Transcribe with OpenAI speech-to-text models.</p>
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
            'language': (str, _("Spoken language hint, e.g. Chinese or en (optional, auto-detected when empty)")),
            'request_timeout': (float, _("Per-chunk request timeout in seconds")),
            'rate_limit': (float, _("Maximum API requests per minute (0 for unlimited)")),
        })
        return options

    def ResolveLanguageCode(self, language : str|None, display_language : str|None = None) -> str|None:
        """Whisper-style endpoints take an ISO 639-1 code ("en", "zh"), or None to auto-detect."""
        locale = self.ResolveLanguageLocale(language, display_language)
        return locale.language if locale is not None else None

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
