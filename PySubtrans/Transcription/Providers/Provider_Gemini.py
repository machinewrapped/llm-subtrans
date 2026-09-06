import importlib.util
import logging
import os
from datetime import timedelta

import regex

from PySubtrans.Helpers.Localization import _
from PySubtrans.Options import SettingsType, env_float
from PySubtrans.SettingsType import GuiSettingsType, SettingsType
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.Transcription.TranscriptionAligner import WordTiming
from PySubtrans.Transcription.TranscriptionClient import TranscriptionClient
from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider

# Quota responses carry a "Please retry in Ns" hint, sometimes compound
# ("11h55m6s" for daily quotas). See rate-limits docs.
_RETRY_HINT_PATTERN = regex.compile(
    r'retry in\s+(?:(\d+)\s*h\s*)?(?:(\d+)\s*m\s*)?(\d+(?:\.\d+)?)\s*s',
    regex.IGNORECASE)

# Fallback backoff when the quota response carries no retry hint
_RETRY_BASE_SECONDS = 5.0
_RETRY_MAX_SECONDS = 120.0

# Hints beyond this are "come back later", not "wait it out"
_RETRY_GIVE_UP_SECONDS = 600.0


def _is_rate_limit_error(error : Exception) -> bool:
    """
    Whether a backend failure is a 429 quota response worth retrying.

    Matches the SDK error type when importable, otherwise duck-types on
    status attributes and message markers (SDK internals move around).
    """
    if getattr(error, 'code', None) == 429 or getattr(error, 'status_code', None) == 429:
        return True

    try:
        from google.genai import errors as genai_errors
        api_error = getattr(genai_errors, 'APIError', None)
        if api_error is not None and isinstance(error, api_error):
            return getattr(error, 'code', None) == 429
    except ImportError:
        pass

    message = str(error).casefold()
    return ('error code: 429' in message or 'too_many_requests' in message
            or ('429' in message and ('rate' in message or 'quota' in message or 'retry' in message)))


def _retry_hint_seconds(error : Exception) -> float|None:
    """
    Raw "retry in ..." hint from a quota response, handling compound
    durations ("11h55m6s") as well as plain seconds. None when absent.
    """
    match = _RETRY_HINT_PATTERN.search(str(error))
    if not match:
        return None
    try:
        hours = float(match.group(1) or 0.0)
        minutes = float(match.group(2) or 0.0)
        seconds = float(match.group(3))
        return max(0.0, hours * 3600.0 + minutes * 60.0 + seconds)
    except ValueError:
        return None


def _rate_limit_delay_seconds(error : Exception, attempt : int) -> float:
    """
    Backoff before retrying a quota response: honour the server's retry
    hint when present, otherwise exponential fallback (5s doubling to 120s).
    """
    hint = _retry_hint_seconds(error)
    if hint is not None:
        return min(hint, _RETRY_MAX_SECONDS)

    return min(_RETRY_BASE_SECONDS * (2 ** attempt), _RETRY_MAX_SECONDS)


def _format_retry_delay(seconds : float) -> str:
    """Human-readable backoff for quota messages ("about 12 hours")."""
    total = int(round(max(0.0, seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"about {hours} hour{'s' if hours != 1 else ''}"
    if minutes:
        return f"about {minutes} minute{'s' if minutes != 1 else ''}"
    return f"about {secs} second{'s' if secs != 1 else ''}"

# Free-text hints to BCP-47 codes (empty/unknown hints use auto-detection)
_GEMINI_LANGUAGE_MAP : dict[str, str] = {
    'chinese': 'cmn-Hans-CN',
    'mandarin': 'cmn-Hans-CN',
    'cantonese': 'yue-Hant-HK',
    'yue': 'yue-Hant-HK',
    'english': 'en-US',
    'japanese': 'ja-JP',
    'korean': 'ko-KR',
    'french': 'fr-FR',
    'german': 'de-DE',
    'spanish': 'es-ES',
    'italian': 'it-IT',
    'portuguese': 'pt-BR',
    'russian': 'ru-RU',
    'hindi': 'hi-IN',
    'arabic': 'ar-EG',
    'thai': 'th-TH',
    'vietnamese': 'vi-VN',
}


def map_language_code(language : str|None) -> str|None:
    """
    Map a free-text language hint onto a BCP-47 code, passing through
    values that already look like codes. None enables auto-detection.
    """
    if not language or not language.strip():
        return None

    hint = language.strip()
    if '-' in hint:
        return hint

    return _GEMINI_LANGUAGE_MAP.get(hint.casefold())


def parse_offset(value : object) -> float|None:
    """
    Parse Gemini time offsets ("1.200s", "3s") into seconds.
    """
    if value is None:
        return None
    try:
        text = str(value).strip().removesuffix('s')
        return max(0.0, float(text))
    except (TypeError, ValueError):
        return None


def parse_word_annotations(annotations : list) -> list[WordTiming]:
    """
    Extract word timings from word_info annotations.

    Pure function over annotation shapes so it is unit-testable without
    the Google SDK installed.
    """
    words : list[WordTiming] = []
    for annotation in annotations or []:
        if getattr(annotation, 'type', None) != 'word_info':
            continue
        text = str(getattr(annotation, 'text', '') or '').strip()
        start = parse_offset(getattr(annotation, 'start_offset', None))
        end = parse_offset(getattr(annotation, 'end_offset', None))
        if not text or start is None or end is None or end <= start:
            continue
        speaker = getattr(annotation, 'speaker', None)
        words.append(WordTiming(text=text,
                                start=timedelta(seconds=start),
                                end=timedelta(seconds=end),
                                speaker=str(speaker) if speaker else None))

    words.sort(key=lambda w: w.start)
    return words


def collect_word_annotations(interaction : object) -> list:
    """
    Gather word_info annotations from interaction steps.
    """
    words : list = []
    for step in getattr(interaction, 'steps', []) or []:
        for content in getattr(step, 'content', []) or []:
            for annotation in getattr(content, 'annotations', []) or []:
                if getattr(annotation, 'type', None) == 'word_info':
                    words.append(annotation)

    return words


if not importlib.util.find_spec("google"):
    logging.debug(_("Google SDK (google-genai) is not installed. Gemini transcription will not be available"))
else:
    try:
        class GeminiTranscriptionProvider(TranscriptionProvider):
            """
            Speech-to-text via Gemini 3.5 Transcribe with word timestamps
            and speaker diarization. Only registered when google-genai is
            installed; shares the translation API key.
            """
            name = "Gemini"

            information = """
            <p>Transcribe with Gemini 3.5 Transcribe (word timestamps, speaker diarization).</p>
            <p>Requires a <a href="https://aistudio.google.com/app/apikey">Google AI Studio API key</a>.</p>
            """

            @property
            def recommended_min_chunk_seconds(self) -> float:
                """Long chunks amortise per-request overhead, keep speaker identities stable and stay under daily request quotas."""
                return 180.0

            @property
            def recommended_max_chunk_seconds(self) -> float:
                """The Files API handles multi-minute chunks comfortably."""
                return 600.0

            def __init__(self, settings : SettingsType):
                super().__init__(self.name, SettingsType({
                    'api_key': settings.get_str('api_key', os.getenv('GEMINI_API_KEY')),
                    'model': settings.get_str('model', os.getenv('GEMINI_STT_MODEL', 'gemini-3.5-transcribe')),
                    'language': settings.get_str('language', os.getenv('TRANSCRIPTION_LANGUAGE')),
                    'diarize': settings.get_bool('diarize', True),
                    'max_retries': settings.get_int('max_retries', 5),
                    'rate_limit': settings.get_float('rate_limit', env_float('GEMINI_TRANSCRIPTION_RATE_LIMIT')),
                }))

            def GetAvailableModels(self) -> list[str]:
                """Transcription models served by this provider."""
                return ['gemini-3.5-transcribe']

            def GetTranscriptionClient(self, settings : SettingsType) -> TranscriptionClient:
                """Returns a new client merging provider defaults with call settings."""
                # Sanctioned lazy import: the client module pulls google-genai,
                # so it loads on first use, not on registration.
                try:
                    from PySubtrans.Transcription.Providers.Clients.GeminiTranscriptionClient import GeminiTranscriptionClient
                except ImportError as e:
                    raise SubtitleError(_("Gemini transcription runtime is not installed"), error=e)
                client_settings = SettingsType(self.settings.copy())
                client_settings.update(settings)
                return GeminiTranscriptionClient(client_settings)

            def GetOptions(self, settings : SettingsType) -> GuiSettingsType:
                """Returns the configurable options for the provider."""
                return {
                    'api_key': (str, _("A Google AI Studio API key (shared with translation)")),
                    'model': (self.available_models, _("Speech-to-text model")),
                    'language': (str, _("Spoken language hint, e.g. Chinese or cmn-Hans-CN (optional, auto-detected when empty)")),
                    'diarize': (bool, _("Identify speakers (up to 8, experimental past 3)")),
                    'max_retries': (int, _("Rate-limit retries per chunk before giving up")),
                    'rate_limit': (float, _("Maximum API requests per minute (0 for unlimited)")),
                }

            def ValidateSettings(self) -> bool:
                """Validate the settings for the provider."""
                if not self.settings.get_str('api_key'):
                    self.validation_message = _("API Key is required")
                    return False

                return True

    except ImportError as e:
        logging.debug(_("google-genai dependencies missing, Gemini transcription unavailable ({})").format(e))
