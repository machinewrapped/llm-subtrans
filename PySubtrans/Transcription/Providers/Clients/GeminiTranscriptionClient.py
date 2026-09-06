import importlib.util
import logging
import os
import tempfile
from typing import Any

from PySubtrans.Helpers.Localization import _
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.Transcription.TranscriptionClient import TranscriptionClient
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionResult
from PySubtrans.Transcription.Providers.Provider_Gemini import (
    _RETRY_GIVE_UP_SECONDS,
    _format_retry_delay,
    _is_rate_limit_error,
    _rate_limit_delay_seconds,
    _retry_hint_seconds,
    collect_word_annotations,
    map_language_code,
    parse_word_annotations,
)


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

            def _transcribe_chunk(self, audio_bytes : bytes, audio_format : str, language : str|None) -> TranscriptionResult:
                client = genai.Client(api_key=self.api_key)
                chunk_path = self._write_chunk(audio_bytes)
                audio_file = None
                try:
                    result_interaction, audio_file = self._create_interaction(client, chunk_path, language)
                except SubtitleError:
                    raise
                except Exception as e:
                    raise SubtitleError(_("Gemini transcription failed: {}").format(str(e)), error=e)
                finally:
                    try:
                        os.remove(chunk_path)
                    except OSError:
                        pass
                    if audio_file is not None:
                        file_name = getattr(audio_file, 'name', None)
                        if file_name:
                            try:
                                client.files.delete(name=file_name)
                            except Exception as e:
                                logging.warning(_("Unable to delete uploaded audio: {}").format(str(e)))
                        else:
                            logging.debug(_("Uploaded audio has no name; leaving it to expire"))

                text = str(getattr(result_interaction, 'output_text', '') or '').strip()
                if not text:
                    raise SubtitleError(_("Transcription returned no text"))

                words = parse_word_annotations(collect_word_annotations(result_interaction))
                return TranscriptionResult(text=text, language=language, words=words)

            def _create_interaction(self, client : Any, chunk_path : str, language : str|None) -> tuple[Any, Any]:
                """
                Upload once, then retry transcription on quota responses.

                Reuses the uploaded file across attempts (quota applies to
                generation, not storage) and honours the server's retry hint.
                """
                audio_file = None
                attempt = 0
                while True:
                    if self.aborted:
                        raise SubtitleError(_("Transcription aborted"))
                    try:
                        if audio_file is None:
                            audio_file = client.files.upload(file=chunk_path)
                        interaction = client.interactions.create(
                            model=self.model,
                            input=[{
                                "type": "audio",
                                "uri": audio_file.uri,
                                "mime_type": "audio/wav",
                            }],
                            generation_config={"transcription_config": self._transcription_config(language)},
                        )
                        return interaction, audio_file
                    except Exception as e:
                        if self.aborted:
                            raise SubtitleError(_("Transcription aborted"))
                        if not _is_rate_limit_error(e) or attempt >= self.max_retries:
                            if _is_rate_limit_error(e):
                                raise SubtitleError(_(
                                    "Gemini rate limit still exceeded after {} attempts: {}"
                                ).format(attempt + 1, str(e)[:200]), error=e)
                            raise
                        hint = _retry_hint_seconds(e)
                        if hint is not None and hint > _RETRY_GIVE_UP_SECONDS:
                            raise SubtitleError(_(
                                "Gemini quota exceeded, retry in {}"
                            ).format(_format_retry_delay(hint)), error=e)
                        delay = _rate_limit_delay_seconds(e, attempt)
                        logging.warning(_("Gemini rate limit hit (attempt {}/{}), retrying in {:.0f}s").format(
                            attempt + 1, self.max_retries + 1, delay))
                        self._sleep_abortable(delay)
                        attempt += 1

            def _transcription_config(self, language : str|None) -> dict:
                mode : dict = {"type": "verbatim", "timestamp_granularities": ["word"]}
                if self.diarize:
                    mode["diarization_mode"] = "speaker"

                config : dict = {"mode": mode}
                code = map_language_code(language)
                if code:
                    config["language_codes"] = [code]

                return config

            def _write_chunk(self, audio_bytes : bytes) -> str:
                handle, path = tempfile.mkstemp(suffix='.wav', prefix='subtrans-gemini-')
                with os.fdopen(handle, 'wb') as f:
                    f.write(audio_bytes)
                return path

    except ImportError as e:
        logging.debug(_("google-genai dependencies missing, Gemini transcription unavailable ({})").format(e))
