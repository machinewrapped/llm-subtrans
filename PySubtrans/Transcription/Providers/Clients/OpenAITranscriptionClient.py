import json
from datetime import timedelta

import httpx

from PySubtrans.Helpers.Localization import _
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.Transcription.TranscriptionClient import TranscriptionClient
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionResult
from PySubtrans.Transcription.Providers.Provider_OpenAI import (
    _to_seconds,
    parse_diarized_payload,
    parse_verbose_payload,
)


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

    def _transcribe_chunk(self, audio_bytes : bytes, audio_format : str, language : str|None) -> TranscriptionResult:
        if self.supports_diarization:
            return self._request_diarized(audio_bytes, language)
        return self._request_verbose(audio_bytes, language)

    def _request_verbose(self, audio_bytes : bytes, language : str|None) -> TranscriptionResult:
        payload = self._post({
            'model': (None, self.model),
            'response_format': (None, 'verbose_json'),
            'timestamp_granularities[]': (None, 'word'),
            **self._language_fields(language),
            'file': ('chunk.wav', audio_bytes, 'audio/wav'),
        })
        text, detected, words = parse_verbose_payload(payload)
        if not text:
            raise SubtitleError(_("Transcription returned no text"))
        result = TranscriptionResult(text=text, language=detected or language, words=words)
        return self._attach_usage(result, payload)

    def _request_diarized(self, audio_bytes : bytes, language : str|None) -> TranscriptionResult:
        payload = self._post({
            'model': (None, self.model),
            'response_format': (None, 'diarized_json'),
            'chunking_strategy': (None, 'auto'),
            **self._language_fields(language),
            'file': ('chunk.wav', audio_bytes, 'audio/wav'),
        })
        text, parts = parse_diarized_payload(payload)
        if not text:
            raise SubtitleError(_("Transcription returned no text"))
        result = TranscriptionResult(text=text, language=language, parts=parts)
        return self._attach_usage(result, payload)

    def _language_fields(self, language : str|None) -> dict:
        if not language:
            return {}
        return {'language': (None, language)}

    def _attach_usage(self, result : TranscriptionResult, payload : dict) -> TranscriptionResult:
        """
        Attach duration when the response reports it.
        """
        seconds = _to_seconds(payload.get('duration'))
        if seconds is not None:
            result.duration = timedelta(seconds=seconds)

        return result

    def _post(self, fields : dict) -> dict:
        url = f"{self.server_address}/audio/transcriptions"
        headers = {'Authorization': f"Bearer {self.api_key}"} if self.api_key else {}

        proxy = self.settings.get_str('proxy')
        try:
            with httpx.Client(timeout=self.request_timeout, proxy=proxy) as client:
                response = client.post(url, headers=headers, files=fields)
        except Exception as e:
            raise SubtitleError(_("Transcription request failed: {}").format(str(e)), error=e)

        if response.is_error:
            reply = (response.text or '').strip()
            if reply.startswith(('{', '[')):
                detail = reply[:500]
            elif reply:
                detail = _("non-JSON response (check the Server address): {}").format(reply[:200])
            else:
                detail = _("empty response body")
            raise SubtitleError(_("Transcription request failed: POST {} returned {}: {}").format(
                url, response.status_code, detail))

        text = (response.text or '').strip()
        if not text.startswith(('{', '[')):
            raise SubtitleError(_("Transcription failed ({}): non-JSON response: {}").format(
                response.status_code, text[:200]))

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as e:
            raise SubtitleError(_("Unable to parse transcription response"), error=e)

        if not isinstance(payload, dict):
            raise SubtitleError(_("Unexpected transcription response shape"))

        return payload
