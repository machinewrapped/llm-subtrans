import base64
import json
import logging
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
        start = _to_seconds(entry.get('start'))
        end = _to_seconds(entry.get('end'))
        if not entry_text or start is None or end is None or end <= start:
            continue
        speaker = entry.get('speaker')
        no_speech_prob = _to_seconds(entry.get('no_speech_prob'))
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
        start = _to_seconds(entry.get('start'))
        end = _to_seconds(entry.get('end'))
        if not word_text or start is None or end is None or end <= start:
            continue
        speaker = entry.get('speaker')
        words.append(WordTiming(text=word_text,
                                start=timedelta(seconds=start),
                                end=timedelta(seconds=end),
                                speaker=str(speaker) if speaker is not None else None))

    words.sort(key=lambda w: w.start)
    return text, language, parts, words


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


class OpenRouterTranscriptionProvider(TranscriptionProvider):
    """
    Speech-to-text via OpenRouter with the shared account API key.
    """
    name = "OpenRouter"

    information = """
    <p>Transcribe with OpenRouter speech-to-text models over one API key.</p>
    <p>Word timestamps and diarization depend on the selected model.</p>
    """

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
                'microsoft/mai-transcribe-2', 'google/chirp-3']

    def GetTranscriptionClient(self, settings : SettingsType) -> TranscriptionClient:
        """Returns a new client merging provider defaults with call settings."""
        client_settings = SettingsType(self.settings.copy())
        client_settings.update(settings)
        return OpenRouterTranscriptionClient(client_settings)

    def GetOptions(self, settings : SettingsType) -> GuiSettingsType:
        """Returns the configurable options for the provider."""
        return {
            'api_key': (str, _("An OpenRouter API key (shared with translation)")),
            'model': (self.available_models, _("Speech-to-text model")),
            'language': (str, _("Spoken language hint, e.g. en or Chinese (optional)")),
            'diarize': (bool, _("Request speaker diarization (only supported by some models)")),
            'request_timeout': (float, _("Per-chunk request timeout in seconds")),
            'rate_limit': (float, _("Maximum API requests per minute (0 for unlimited)")),
        }

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
