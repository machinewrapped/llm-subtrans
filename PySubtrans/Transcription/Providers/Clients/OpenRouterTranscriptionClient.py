import base64
import json
import logging
from datetime import timedelta

import httpx

from PySubtrans.Helpers.Localization import _
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.Transcription.TranscriptionClient import TranscriptionClient
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionResult
from PySubtrans.Transcription.Providers.Provider_OpenRouter import (
    _to_seconds,
    parse_transcription_payload,
)


class OpenRouterTranscriptionClient(TranscriptionClient):
    """
    Speech-to-text via OpenRouter's /audio/transcriptions endpoint.

    Requests verbose_json with word timestamps first; providers that
    reject structured output fall back to plain text (chunk-level lines).
    Diarization is a per-model provider option (see _diarize_options).
    """
    def __init__(self, settings : SettingsType):
        super().__init__(settings)

    @property
    def server_address(self) -> str:
        """Base URL of the OpenRouter API."""
        address = self.settings.get_str('server_address') or 'https://openrouter.ai/api/v1'
        return address.rstrip('/')

    @property
    def api_key(self) -> str|None:
        """OpenRouter API key (shared with the translation provider)."""
        return self.settings.get_str('api_key')

    @property
    def model(self) -> str:
        """STT model slug, e.g. openai/whisper-large-v3."""
        return self.settings.get_str('model') or 'openai/whisper-large-v3'

    @property
    def diarize(self) -> bool:
        """Whether speaker diarization is requested (model-dependent)."""
        return self.settings.get_bool('diarize', False)

    @property
    def supports_timestamps(self) -> bool:
        """Verbose timestamps are negotiated per request (with fallback)."""
        return True

    @property
    def supports_diarization(self) -> bool:
        """Speaker labels when diarization is requested on a mapped model."""
        return self.diarize

    def _transcribe_chunk(self, audio_bytes : bytes, audio_format : str, language : str|None) -> TranscriptionResult:
        # No silent plain-text fallback: without timings the result has no
        # value as subtitle input, and the retry would bill a second request.
        # Note: SubtitleError.__str__ prefers the wrapped error, so the
        # provider detail is embedded in the message itself to stay visible.
        try:
            return self._request_verbose(audio_bytes, language)
        except _StructuredOutputUnsupported as e:
            detail = str(e)[:200] if str(e) else ""
            raise SubtitleError(_(
                "Model '{}' does not support timestamped transcription "
                "(verbose_json was rejected{}). Choose a model with timestamp "
                "support instead of spending credits on untimed text."
            ).format(self.model, f": {detail}" if detail else ""))

    def _request_verbose(self, audio_bytes : bytes, language : str|None) -> TranscriptionResult:
        # Empty text is an expected outcome (music, silence, noise), not an
        # error: return it and let the coordinator skip the chunk quietly.
        payload = self._post(audio_bytes, language)
        text, detected, parts, words = parse_transcription_payload(payload)
        result = TranscriptionResult(text=text, language=detected or language, parts=parts, words=words)
        return self._attach_usage(result, payload)

    def _attach_usage(self, result : TranscriptionResult, payload : dict) -> TranscriptionResult:
        """
        Attach duration and billed cost from the usage block when present.
        """
        seconds = _to_seconds(payload.get('duration'))
        if seconds is not None:
            result.duration = timedelta(seconds=seconds)

        usage = payload.get('usage')
        if isinstance(usage, dict):
            cost = _to_seconds(usage.get('cost'))
            if cost is not None:
                result.cost = cost

        return result

    def _post(self, audio_bytes : bytes, language : str|None) -> dict:
        url = f"{self.server_address}/audio/transcriptions"
        headers = {'Authorization': f"Bearer {self.api_key}"} if self.api_key else {}
        body : dict = {
            'model': self.model,
            'input_audio': {'data': base64.b64encode(audio_bytes).decode('ascii'), 'format': 'wav'},
            'response_format': 'verbose_json',
            'timestamp_granularities': ['word'],
        }
        if language:
            body['language'] = language
        options = self._diarize_options()
        if options:
            body['provider'] = {'options': options}

        proxy = self.settings.get_str('proxy')
        try:
            with httpx.Client(timeout=self.request_timeout, proxy=proxy) as client:
                response = client.post(url, headers=headers, json=body)
        except Exception as e:
            raise SubtitleError(_("Transcription request failed: {}").format(str(e)), error=e)

        if response.status_code == 400 and self._looks_like_unsupported(response.text):
            raise _StructuredOutputUnsupported(response.text[:200])

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

        # Peek before parsing: gateways and proxies answer failures with
        # HTML pages, which json.loads would report only cryptically.
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

    def _diarize_options(self) -> dict:
        """
        Map the generic diarize flag onto provider-specific options.

        Diarization is not a top-level OpenRouter field; each vendor
        exposes it under its own provider slug.
        """
        if not self.diarize:
            return {}

        model_cf = self.model.casefold()
        if model_cf.startswith('microsoft/'):
            return {'azure': {'diarization': {'enabled': True}}}
        if model_cf.startswith('deepgram/'):
            return {'deepgram': {'diarize': True}}

        logging.warning(_("Diarization is not mapped for model '{}', requesting without it").format(self.model))
        return {}

    def _looks_like_unsupported(self, text : str) -> bool:
        lowered = text.casefold()
        return 'verbose_json' in lowered or 'timestamp' in lowered or 'response_format' in lowered


class _StructuredOutputUnsupported(Exception):
    """Provider rejected verbose_json/word timestamps (expected on some models)."""
