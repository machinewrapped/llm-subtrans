from datetime import timedelta

from PySubtrans.Helpers.Localization import _
from PySubtrans.Helpers.Parse import TryParseNonNegative
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.Transcription.TranscriptionClient import TranscriptionClient
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionResult, TranscriptionSegment
from PySubtrans.Transcription.WordTiming import WordTiming


class OpenAITranscriptionClient(TranscriptionClient):
    """
    Speech-to-text via OpenAI's /audio/transcriptions endpoint (multipart).

    Two timed modes: whisper-1 with verbose word timestamps, and
    gpt-4o-transcribe-diarize with speaker segments (chunking_strategy
    auto, required past 30 seconds). The plain gpt-transcribe family
    returns no timings and is refused at validation, not here.
    """
    def __init__(self, settings : SettingsType):
        super().__init__(settings)

    @property
    def server_address(self) -> str:
        """Base URL of the OpenAI API."""
        address = self.settings.get_str('server_address') or 'https://api.openai.com/v1'
        return address.rstrip('/')

    @property
    def api_key(self) -> str|None:
        """OpenAI API key (shared with the translation provider)."""
        return self.settings.get_str('api_key')

    @property
    def model(self) -> str:
        """Transcription model id."""
        return self.settings.get_str('model') or 'whisper-1'

    @property
    def supports_timestamps(self) -> bool:
        """Both served models return timings in their timed formats."""
        return True

    @property
    def supports_diarization(self) -> bool:
        """Speaker labels only from the diarize model."""
        return self.model.strip().casefold() == 'gpt-4o-transcribe-diarize'

    def _transcribe_chunk(self, audio_bytes : bytes, audio_format : str) -> TranscriptionResult:
        if self.supports_diarization:
            return self._request_diarized(audio_bytes)
        return self._request_verbose(audio_bytes)

    def _request_verbose(self, audio_bytes : bytes) -> TranscriptionResult:
        payload = self._post({
            'model': (None, self.model),
            'response_format': (None, 'verbose_json'),
            'timestamp_granularities[]': (None, 'word'),
            **self._language_fields(),
            'file': ('chunk.wav', audio_bytes, 'audio/wav'),
        })

        text, detected, words = parse_verbose_payload(payload)

        if not text:
            raise SubtitleError(_("Transcription returned no text"))

        result = TranscriptionResult(text=text, language=detected or self.language, words=words)
        return self._attach_usage(result, payload)

    def _request_diarized(self, audio_bytes : bytes) -> TranscriptionResult:
        payload = self._post({
            'model': (None, self.model),
            'response_format': (None, 'diarized_json'),
            'chunking_strategy': (None, 'auto'),
            **self._language_fields(),
            'file': ('chunk.wav', audio_bytes, 'audio/wav'),
        })

        text, parts = parse_diarized_payload(payload)

        if not text:
            raise SubtitleError(_("Transcription returned no text"))

        result = TranscriptionResult(text=text, language=self.language, parts=parts)
        return self._attach_usage(result, payload)

    def _language_fields(self) -> dict:
        if not self.language:
            return {}
        return {'language': (None, self.language)}

    def _attach_usage(self, result : TranscriptionResult, payload : dict) -> TranscriptionResult:
        """
        Attach duration when the response reports it.
        """
        seconds = TryParseNonNegative(payload.get('duration'))
        if seconds is not None:
            result.duration = timedelta(seconds=seconds)

        return result

    def _post(self, fields : dict) -> dict:
        url = f"{self.server_address}/audio/transcriptions"
        headers = {'Authorization': f"Bearer {self.api_key}"} if self.api_key else {}

        return self._PostJson(url, headers=headers, files=fields)


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
        start = TryParseNonNegative(entry.get('start'))
        end = TryParseNonNegative(entry.get('end'))
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
        start = TryParseNonNegative(entry.get('start'))
        end = TryParseNonNegative(entry.get('end'))
        if not word_text or start is None or end is None or end <= start:
            continue
        words.append(WordTiming(text=word_text,
                                start=timedelta(seconds=start),
                                end=timedelta(seconds=end)))

    words.sort(key=lambda w: w.start)
    return text, language, words
