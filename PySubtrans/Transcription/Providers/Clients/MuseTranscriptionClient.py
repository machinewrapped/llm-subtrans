import json
from datetime import timedelta

from PySubtrans.Helpers.Localization import _
from PySubtrans.Helpers.Parse import TryParseNonNegative
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.Transcription.TranscriptionClient import TranscriptionClient
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionResult, TranscriptionSegment


class MuseTranscriptionClient(TranscriptionClient):
    """
    Speech-to-text via the Muse Voice Transcribe one-shot endpoint.

    Each chunk is POSTed as multipart (request JSON plus WAV audio) and the
    turns come back with start/end offsets and speaker labels. Turn-level
    timings only: no word timestamps.
    """
    def __init__(self, settings : SettingsType):
        super().__init__(settings)

    @property
    def server_address(self) -> str:
        """Base URL of the Meta Model API."""
        address = self.settings.get_str('server_address') or 'https://api.meta.ai/v1'
        return address.rstrip('/')

    @property
    def api_key(self) -> str|None:
        """Meta Model API key."""
        return self.settings.get_str('api_key')

    @property
    def model(self) -> str:
        """Transcription model id."""
        return self.settings.get_str('model') or 'muse-voice-transcribe-1.0'

    @property
    def diarize(self) -> bool:
        """Whether speaker diarization is requested (DIARIZATION mode)."""
        return self.settings.get_bool('diarize', False)

    @property
    def supports_timestamps(self) -> bool:
        """Turns carry start and end offsets (DIARIZATION is always requested)."""
        return True

    @property
    def supports_diarization(self) -> bool:
        """Speaker labels are kept only when diarization is opted into."""
        return self.diarize

    def _transcribe_chunk(self, audio_bytes : bytes, audio_format : str) -> TranscriptionResult:
        payload = self._post(audio_bytes)

        text, parts = parse_muse_payload(payload, include_speakers=self.diarize)

        if not text and not parts:
            raise SubtitleError(_("Transcription returned no text"))

        result = TranscriptionResult(text=text, language=self.language, parts=parts)
        return self._attach_usage(result, payload)

    def _request_config(self) -> dict:
        """
        Request JSON part: DIARIZATION always, since PUSH_TO_TALK returns
        flat text with no turn timings to build subtitles from.
        """
        config : dict = {
            'mode': 'DIARIZATION',
            'model': self.model,
            'audioEncoding': 'WAV',
        }
        if self.language:
            config['languageBias'] = [self.language]

        return config

    def _attach_usage(self, result : TranscriptionResult, payload : dict) -> TranscriptionResult:
        """
        Attach duration when the response reports it.
        """
        duration_ms = TryParseNonNegative(payload.get('audioDurationMs'))
        if duration_ms is not None:
            result.duration = timedelta(seconds=duration_ms / 1000.0)

        return result

    def _post(self, audio_bytes : bytes) -> dict:
        url = f"{self.server_address}/asr/transcribe"
        headers = {'Authorization': f"Bearer {self.api_key}"} if self.api_key else {}
        fields = {
            'request': (None, json.dumps(self._request_config()), 'application/json'),
            'audio': ('chunk.wav', audio_bytes, 'audio/wav'),
        }

        response = self._PostRequest(url, headers=headers, files=fields)

        # Intercept before the generic handler to provide Muse-specific
        # status-code hints from the cookbook.
        if response.is_error:
            raise SubtitleError(_("Transcription request failed: POST {} returned {}: {}").format(
                url, response.status_code, self._error_hint(response)))

        return self._ParseJsonResponse(url, response)

    def _error_hint(self, response) -> str:
        """Map cookbook-documented status codes to actionable hints."""
        reply = (response.text or '').strip()
        detail = reply[:500] if reply.startswith(('{', '[')) else (reply[:200] if reply else _("empty response body"))

        hints = {
            400: _("audio over the 10-minute cap, or a malformed request"),
            401: _("the credential was not accepted"),
            404: _("endpoint not found"),
            413: _("body over 32 MB"),
            429: _("rate limited"),
        }
        hint = hints.get(response.status_code)

        if hint is None:
            return detail
        return f"{hint}: {detail}"


def parse_muse_payload(payload : dict, chunk_seconds : float|None = None, include_speakers : bool = True) -> tuple[str, list[TranscriptionSegment]]:
    """
    Extract (text, parts) from a Muse Voice Transcribe response.

    Pure function over the one-shot shape so it is unit-testable without
    network access. Turns carry start and end offsets with speaker labels
    (bare letters in DIARIZATION); a turn missing its end runs until the
    next turn starts, the last one until the reported audio duration.
    """
    text = str(payload.get('transcript') or payload.get('text') or '').strip()

    duration_ms = TryParseNonNegative(payload.get('audioDurationMs'))
    audio_seconds = (duration_ms / 1000.0) if duration_ms is not None else chunk_seconds

    turns = [entry for entry in payload.get('turns') or [] if isinstance(entry, dict)]

    starts : list[float|None] = []
    for entry in turns:
        start_ms = TryParseNonNegative(entry.get('startMs'))
        starts.append(start_ms / 1000.0 if start_ms is not None else None)

    parts : list[TranscriptionSegment] = []
    for index, entry in enumerate(turns):
        entry_text = str(entry.get('transcript') or entry.get('text') or '').strip()
        start = starts[index]

        if not entry_text or start is None:
            continue

        end_ms = TryParseNonNegative(entry.get('endMs'))
        end = end_ms / 1000.0 if end_ms is not None else None

        if end is None:
            end = next((s for s in starts[index + 1:] if s is not None and s > start), None)
        if end is None:
            end = audio_seconds

        if end is None or end <= start:
            continue

        speaker = entry.get('speaker') if include_speakers else None
        parts.append(TranscriptionSegment(
            start=timedelta(seconds=start), end=timedelta(seconds=end),
            text=entry_text,
            speaker=str(speaker) if speaker is not None else None))

    parts.sort(key=lambda part: part.start)

    return text, parts


