import importlib.util
import logging
import os
import tempfile
from datetime import timedelta
from typing import Any

import regex

from PySubtrans.Helpers.Localization import _
from PySubtrans.Helpers.Parse import TryParseFloat
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.Transcription.TranscriptionClient import TranscriptionClient
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionResult
from PySubtrans.Transcription.WordTiming import WordTiming

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
    hours = TryParseFloat(match.group(1) or 0.0)
    minutes = TryParseFloat(match.group(2) or 0.0)
    seconds = TryParseFloat(match.group(3))
    if seconds is None:
        return None
    return max(0.0, (hours or 0.0) * 3600.0 + (minutes or 0.0) * 60.0 + seconds)


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


def parse_offset(value : object) -> float|None:
    """
    Parse Gemini time offsets ("1.200s", "3s") into seconds.
    """
    if value is None:
        return None
    text = str(value).strip().removesuffix('s')
    parsed = TryParseFloat(text)
    return max(0.0, parsed) if parsed is not None else None


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
        from google import genai


        class GeminiTranscriptionClient(TranscriptionClient):
            """
            Speech-to-text via Gemini 3.5 Transcribe (Interactions API).

            Each chunk is uploaded through the Files API, transcribed with
            verbatim word timestamps and speaker diarization, then deleted.
            Heavy SDK imports stay inside methods so constructing the client
            never touches google-genai.
            """
            def __init__(self, settings : SettingsType):
                super().__init__(settings)

            @property
            def api_key(self) -> str|None:
                """Google AI Studio API key (shared with translation)."""
                return self.settings.get_str('api_key')

            @property
            def model(self) -> str:
                """Transcription model id."""
                return self.settings.get_str('model') or 'gemini-3.5-transcribe'

            @property
            def diarize(self) -> bool:
                """Whether speaker diarization is requested."""
                return self.settings.get_bool('diarize', True)

            @property
            def max_retries(self) -> int:
                """Rate-limit retries per chunk before giving up."""
                return self.settings.get_int('max_retries', 5) or 0

            @property
            def supports_timestamps(self) -> bool:
                return True

            @property
            def supports_diarization(self) -> bool:
                """Speaker labels only in verbatim mode with diarization enabled."""
                return self.diarize

            # Transcription

            def _transcribe_chunk(self, audio_bytes : bytes, audio_format : str) -> TranscriptionResult:
                client = genai.Client(api_key=self.api_key)
                chunk_path = self._write_chunk(audio_bytes)
                audio_file = None

                try:
                    logging.info(_("Uploading audio chunk for Gemini transcription"))
                    audio_file = client.files.upload(file=chunk_path)

                    result_interaction = self._create_interaction(client, audio_file)

                    text = str(getattr(result_interaction, 'output_text', '') or '').strip()
                    if not text:
                        raise SubtitleError(_("Transcription returned no text"))

                    words = parse_word_annotations(collect_word_annotations(result_interaction))
                    return TranscriptionResult(text=text, language=self.language, words=words)
                except SubtitleError:
                    raise
                except Exception as e:
                    raise SubtitleError(_("Gemini transcription failed: {}").format(str(e)), error=e)
                finally:
                    self._delete_uploaded_audio(client, audio_file)

                    try:
                        os.remove(chunk_path)
                    except OSError:
                        pass

            def _create_interaction(self, client : Any, audio_file : Any) -> Any:
                """
                Retry transcription on quota responses.

                Reuses the already-uploaded file across attempts (quota applies
                to generation, not storage) and honours the server's retry hint.
                The caller owns the file lifecycle (upload and delete).
                """
                retry_limit = max(0, self.max_retries)

                for attempt in range(retry_limit + 1):
                    if self.aborted:
                        raise SubtitleError(_("Transcription aborted"))

                    try:
                        return client.interactions.create(
                            model=self.model,
                            input=[{
                                "type": "audio",
                                "uri": audio_file.uri,
                                "mime_type": "audio/wav",
                            }],
                            generation_config={"transcription_config": self._transcription_config()},
                        )
                    except Exception as error:
                        delay = self._rate_limit_retry_delay(error, attempt, retry_limit)
                        if delay is None:
                            raise

                        logging.warning(_("Gemini rate limit hit (attempt {}/{}), retrying in {:.0f}s").format(
                            attempt + 1, retry_limit + 1, delay))
                        self._sleep_abortable(delay)

                raise SubtitleError(_("Gemini transcription failed"))

            def _rate_limit_retry_delay(self, error : Exception, attempt : int, retry_limit : int) -> float|None:
                """Return a retry delay, or raise when a failed request cannot be retried."""
                if self.aborted:
                    raise SubtitleError(_("Transcription aborted"))
                if not _is_rate_limit_error(error):
                    return None

                if attempt >= retry_limit:
                    raise SubtitleError(_(
                        "Gemini rate limit still exceeded after {} attempts: {}"
                    ).format(attempt + 1, str(error)[:200]), error=error)

                hint = _retry_hint_seconds(error)
                if hint is not None and hint > _RETRY_GIVE_UP_SECONDS:
                    raise SubtitleError(_(
                        "Gemini quota exceeded, retry in {}"
                    ).format(_format_retry_delay(hint)), error=error)
                return _rate_limit_delay_seconds(error, attempt)

            def _delete_uploaded_audio(self, client : Any, audio_file : Any) -> None:
                """Best-effort cleanup of the uploaded audio file from the Files API."""
                if audio_file is None:
                    return
                file_name = getattr(audio_file, 'name', None)
                if not file_name:
                    logging.debug(_("Uploaded audio has no name; leaving it to expire"))
                    return

                try:
                    client.files.delete(name=file_name)
                except Exception as e:
                    logging.warning(_("Unable to delete uploaded audio: {}").format(str(e)))

            def _transcription_config(self) -> dict:
                """Request config; the language hint is a BCP-47 tag resolved by the provider, or None to auto-detect."""
                language_code = self.language
                mode : dict = {"type": "verbatim", "timestamp_granularities": ["word"]}
                if self.diarize:
                    mode["diarization_mode"] = "speaker"

                config : dict = {"mode": mode}
                if language_code:
                    config["language_codes"] = [language_code]

                return config

            def _write_chunk(self, audio_bytes : bytes) -> str:
                handle, path = tempfile.mkstemp(suffix='.wav', prefix='subtrans-gemini-')

                with os.fdopen(handle, 'wb') as f:
                    f.write(audio_bytes)
                return path

    except ImportError as e:
        logging.debug(_("google-genai dependencies missing, Gemini transcription unavailable ({})").format(e))
