from datetime import timedelta

from PySubtrans.Helpers.Parse import TryParseNonNegative
from PySubtrans.SettingsType import SettingsType
from PySubtrans.Transcription.TranscriptionClient import TranscriptionClient
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionResult
from PySubtrans.Transcription.WordTiming import WordTiming

# Word types that carry text: spoken words, and audio events such as (laughter) when they are tagged
_TIMED_WORD_TYPES = ('word', 'audio_event')

class ElevenLabsTranscriptionClient(TranscriptionClient):
    """
    Speech-to-text via the ElevenLabs /speech-to-text endpoint.

    Sends the audio as a multipart upload and requests word timestamps.
    The response is a transcript plus typed words, with speaker IDs when diarized.
    """
    def __init__(self, settings : SettingsType):
        super().__init__(settings)

    @property
    def server_address(self) -> str:
        """Base URL of the ElevenLabs API."""
        address = self.settings.get_str('server_address') or 'https://api.elevenlabs.io/v1'
        return address.rstrip('/')

    @property
    def api_key(self) -> str|None:
        """ElevenLabs API key."""
        return self.settings.get_str('api_key')

    @property
    def model(self) -> str:
        """Speech-to-text model id."""
        return self.settings.get_str('model') or 'scribe_v2'

    @property
    def supports_timestamps(self) -> bool:
        """Word timestamps are requested for every transcription."""
        return True

    @property
    def supports_diarization(self) -> bool:
        """Speaker labels unless diarization is turned off."""
        return self.settings.get_bool('diarize', True)

    def _transcribe_chunk(self, audio_bytes : bytes, audio_format : str) -> TranscriptionResult:
        # Empty text is an expected outcome (music, silence, noise), not an error
        url = f"{self.server_address}/speech-to-text"
        headers = {'xi-api-key': self.api_key} if self.api_key else {}
        payload = self._PostJson(url, headers=headers, files=self._form_fields(audio_bytes, audio_format))

        text, language, words = _parse_transcription_payload(payload)

        result = TranscriptionResult(text=text, language=language or self.language, words=words)

        seconds = TryParseNonNegative(payload.get('audio_duration_secs'))
        if seconds is not None:
            result.duration = timedelta(seconds=seconds)

        return result

    def _form_fields(self, audio_bytes : bytes, audio_format : str) -> dict:
        """The multipart form for one request."""
        fields : dict = {
            'model_id': (None, self.model),
            'timestamps_granularity': (None, 'word'),
            'diarize': (None, _FormBool(self.supports_diarization)),
            # ElevenLabs tags audio events unless told not to
            'tag_audio_events': (None, _FormBool(self.settings.get_bool('audio_events', False))),
            'file': (f"audio.{audio_format}", audio_bytes, f"audio/{audio_format}"),
        }

        if self.language:
            fields['language_code'] = (None, self.language)

        return fields


def _FormBool(value : bool) -> str:
    """A boolean as a multipart form value."""
    return 'true' if value else 'false'


def _parse_transcription_payload(payload : dict) -> tuple[str, str|None, list[WordTiming]]:
    """
    Extract (text, language, words) from an ElevenLabs speech-to-text response.

    Pure function over the response shape so it is unit-testable without network access.
    Spacing entries are skipped.
    Zero-length words still have a usable start, so only words that end before they start are dropped.
    """
    text = str(payload.get('text') or '').strip()
    language = payload.get('language_code')
    language = str(language).strip() if language else None

    words : list[WordTiming] = []
    for entry in payload.get('words') or []:
        if not isinstance(entry, dict) or entry.get('type', 'word') not in _TIMED_WORD_TYPES:
            continue

        word_text = str(entry.get('text') or '').strip()
        start = TryParseNonNegative(entry.get('start'))
        end = TryParseNonNegative(entry.get('end'))
        if not word_text or start is None or end is None or end < start:
            continue

        speaker = entry.get('speaker_id')
        words.append(WordTiming(text=word_text,
                                start=timedelta(seconds=start),
                                end=timedelta(seconds=end),
                                speaker=str(speaker) if speaker is not None else None))

    return text, language, words
