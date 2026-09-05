import json
import os
from datetime import timedelta

import httpx

from PySubtrans.Helpers.Localization import _
from PySubtrans.Options import SettingsType, env_float
from PySubtrans.SettingsType import GuiSettingsType, SettingsType
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.Transcription.TranscriptionAligner import WordTiming
from PySubtrans.Transcription.TranscriptionClient import TranscriptionClient
from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionResult, TranscriptionSegment


def _to_seconds(value : object) -> float|None:
    try:
        return max(0.0, float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


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


class OpenAITranscriptionProvider(TranscriptionProvider):
    """
    Speech-to-text via OpenAI with the shared account API key.

    Only timed models are served: whisper-1 (word timestamps) and
    gpt-4o-transcribe-diarize (speaker segments). The plain gpt-transcribe
    family returns no timings and is refused at validation.
    """
    name = "OpenAI"

    information = """
    <p>Transcribe with OpenAI speech-to-text models over one API key.</p>
    <p>Useful for spending expiring pay-up-front credits.</p>
    """

    def __init__(self, settings : SettingsType):
        super().__init__(self.name, SettingsType({
            'api_key': settings.get_str('api_key', os.getenv('OPENAI_API_KEY')),
            'server_address': settings.get_str('server_address', os.getenv('OPENAI_SERVER_ADDRESS', 'https://api.openai.com/v1')),
            'model': settings.get_str('model', os.getenv('OPENAI_STT_MODEL', 'whisper-1')),
            'language': settings.get_str('language', os.getenv('TRANSCRIPTION_LANGUAGE')),
            'request_timeout': settings.get_float('request_timeout', env_float('TRANSCRIPTION_TIMEOUT', 300.0)),
            'proxy': settings.get_str('proxy') or os.getenv('OPENAI_PROXY'),
        }))

    def GetAvailableModels(self) -> list[str]:
        """Timed transcription models served by this provider."""
        return ['whisper-1', 'gpt-4o-transcribe-diarize']

    def GetTranscriptionClient(self, settings : SettingsType) -> TranscriptionClient:
        """Returns a new client merging provider defaults with call settings."""
        client_settings = SettingsType(self.settings.copy())
        client_settings.update(settings)
        return OpenAITranscriptionClient(client_settings)

    def GetOptions(self, settings : SettingsType) -> GuiSettingsType:
        """Returns the configurable options for the provider."""
        return {
            'api_key': (str, _("An OpenAI API key (shared with translation)")),
            'model': (self.available_models, _("Speech-to-text model (both return timings)")),
            'language': (str, _("Spoken language hint as ISO code, e.g. en (optional)")),
            'request_timeout': (float, _("Per-chunk request timeout in seconds")),
        }

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
