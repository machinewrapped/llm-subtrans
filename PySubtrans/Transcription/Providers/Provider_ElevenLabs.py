import os

from PySubtrans.Helpers.Localization import _
from PySubtrans.Options import env_float
from PySubtrans.SettingsType import GuiSettingsType, SettingsType
from PySubtrans.Transcription.TranscriptionClient import TranscriptionClient
from PySubtrans.Transcription.TranscriptionProvider import OptionsScope, TranscriptionProvider


class ElevenLabsTranscriptionProvider(TranscriptionProvider):
    """
    Speech-to-text via the ElevenLabs API with an ElevenLabs API key.

    Word timings with speaker labels.
    Splits the clip into chunks by default, or sends it whole in one request.
    """
    name = "ElevenLabs"

    information = _("""
    <p>Requires sufficient credit balance. ElevenLabs Scribe 2 costs about 67 credits per minute.</p>
    """)

    information_noapikey = _("""
    <p>To use this provider you need <a href="https://elevenlabs.io/app/settings/api-keys">an ElevenLabs API key</a> with speech-to-text access.</p>
    """)

    @property
    def supports_diarization(self) -> bool:
        """Speaker labels are kept unless diarization is turned off."""
        return self.settings.get_bool('diarize', True)

    @property
    def transcribe_whole_clip(self) -> bool:
        """Whether the media is sent in one request rather than in chunks."""
        return self.settings.get_bool('transcribe_whole_clip', False)

    def __init__(self, settings : SettingsType):
        super().__init__(self.name, settings)

        # A maximum chunk length of 0 asks for the whole clip, e.g. --max-chunk 0 on the command line
        max_chunk_seconds = settings.get_float('max_chunk_seconds')

        self.settings = SettingsType(self.settings | {
            'api_key': settings.get_str('api_key', os.getenv('ELEVENLABS_API_KEY')),
            'server_address': settings.get_str('server_address', os.getenv('ELEVENLABS_SERVER_ADDRESS', 'https://api.elevenlabs.io/v1')),
            'model': settings.get_str('model', os.getenv('ELEVENLABS_STT_MODEL', 'scribe_v2')),
            'diarize': settings.get_bool('diarize', True),
            'audio_events': settings.get_bool('audio_events', False),
            'transcribe_whole_clip': settings.get_bool('transcribe_whole_clip', max_chunk_seconds == 0),
            'request_timeout': settings.get_float('request_timeout', env_float('TRANSCRIPTION_TIMEOUT', 600.0)),
            'rate_limit': settings.get_float('rate_limit', env_float('ELEVENLABS_TRANSCRIPTION_RATE_LIMIT')),
            'min_chunk_seconds': settings.get_float('min_chunk_seconds', 600.0),
            'max_chunk_seconds': max_chunk_seconds or 900.0,
            'proxy': settings.get_str('proxy') or os.getenv('ELEVENLABS_PROXY'),
        })

        self.refresh_when_changed = ['api_key', 'language', 'diarize', 'audio_events', 'transcribe_whole_clip']

    def _get_provider_information(self, torch_device : str = "Unknown") -> str|None:
        """The provider text, with the trade-offs of the selected transcription mode."""
        base = super()._get_provider_information(torch_device)
        if not self.settings.get_str('api_key'):
            return base

        parts = [base] if base else []

        if self.transcribe_whole_clip:
            if self.supports_diarization:
                parts.append(_("<p><b>Whole clip</b> transcribes the entire file in a single request, keeping speaker labels consistent. "
                               "This may help the translator interpret a line or a scene more correctly, "
                               "but there will be no progress reporting, and a failed request loses the entire clip.</p>"))
            else:
                parts.append(_("<p><b>Whole clip</b> transcribes the entire file in a single request. "
                               "With speaker identification off, there is little reason to do this.</p>"))

        elif self.supports_diarization:
            parts.append(_("<p>Speaker IDs reset with each chunk, which may cause the translator to misinterpret dialogue. "
                           "Transcribing the whole clip may help maintain speaker consistency.</p>"))

        return "\n".join(parts)

    def GetAvailableModels(self) -> list[str]:
        """Speech-to-text models served by this provider."""
        return ['scribe_v2', 'scribe_v1']

    def GetTranscriptionClient(self, settings : SettingsType) -> TranscriptionClient:
        """Returns a new client merging provider defaults with call settings."""
        # Sanctioned lazy import: keeps provider registration light.
        from PySubtrans.Transcription.Providers.Clients.ElevenLabsTranscriptionClient import ElevenLabsTranscriptionClient
        client_settings = SettingsType(self.settings.copy())
        client_settings.update(settings)
        return ElevenLabsTranscriptionClient(client_settings)

    def GetOptions(self, settings : SettingsType, scope : OptionsScope = OptionsScope.ALL) -> GuiSettingsType:
        """
        Returns the configurable options for the provider.
        """
        options : GuiSettingsType = {}

        if scope is OptionsScope.ALL:
            options['api_key'] = (str, _("An ElevenLabs API key"))

        if not self.settings.get_str('api_key'):
            return options

        options.update({
            'model': (self.available_models, _("Speech-to-text model")),
            'language': (str, _("Spoken language hint (auto-detected when empty)")),
            'diarize': (bool, _("Identify speakers")),
            'audio_events': (bool, _("Tag sound effects and music, e.g. [laughter]")),
            'transcribe_whole_clip': (bool, _("Send the whole clip in one request, so speaker labels remain consistent")),
        })

        # Chunk limits only apply when the clip is split
        if not self.transcribe_whole_clip:
            options.update(self._chunk_options())

        if scope is OptionsScope.ALL:
            options['request_timeout'] = (float, _("Request timeout in seconds"))
            options['rate_limit'] = (float, _("Maximum API requests per minute (0 for unlimited)"))
            options.update(self._line_options())

        return options

    def ResolveLanguageCode(self, language : str|None, display_language : str|None = None) -> str|None:
        """ElevenLabs takes an ISO 639-1 or 639-3 code ("ko", "kor"), or None to auto-detect."""
        locale = self.ResolveLanguageLocale(language, display_language)
        return locale.language if locale is not None else None

    def ValidateSettings(self) -> bool:
        """Validate the settings for the provider."""
        if not self.settings.get_str('api_key'):
            self.validation_message = _("API Key is required")
            return False

        return True
