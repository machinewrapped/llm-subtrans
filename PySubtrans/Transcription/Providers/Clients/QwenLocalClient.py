"""Application-side Qwen client using an isolated, reusable model worker."""

import logging
import os
import tempfile
from datetime import timedelta
from threading import RLock
from typing import Any

from PySubtrans.Helpers.Localization import _
from PySubtrans.Helpers.Parse import TryParseFloat
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.Transcription.Torch.Discovery import ResolveEnvironmentPython
from PySubtrans.Transcription.Torch.QwenRuntime import QWEN_ENVIRONMENT_NAME
from PySubtrans.Transcription.TranscriptionClient import TranscriptionClient
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionResult
from PySubtrans.Transcription.WordTiming import WordTiming
from PySubtrans.Transcription.WorkerHost import WorkerError, WorkerHost, WorkerScriptPath

# Clients are recreated between runs, but model loading takes seconds and uses several GB of device memory.
# Keep the worker at module level so the session reuses one ASR model and aligner.
# Retain only the most recent load configuration to bound device memory use.
# The lock covers an entire chunk.
# Abort deliberately bypasses it so cancellation can interrupt a blocked inference request.
_worker_lock = RLock()
_loaded_key : tuple[str, str, str, str, bool]|None = None
_loaded_worker : WorkerHost|None = None
_loaded_ready : dict[str, Any] = {}


class QwenLocalClient(TranscriptionClient):
    """Transcribe temporary WAV chunks with the external environment's Python.

    The session shares one model worker until load settings change.
    Language and timing conversion remain independent of the Qwen SDK.
    """

    def __init__(self, settings : SettingsType):
        super().__init__(settings)
        self._worker : WorkerHost|None = None
        self._language : str|None = self.settings.get_str('language')
        self._device : str|None = None

    @property
    def language(self) -> str|None:
        """The provider's English language hint, validated when the worker loads."""
        return self._language

    @property
    def supports_timestamps(self) -> bool:
        """Word timings are available for aligner-supported languages."""
        return True

    @property
    def checkpoint(self) -> str:
        """ASR checkpoint id."""
        return self.settings.get_str('model') or 'Qwen/Qwen3-ASR-1.7B'

    @property
    def aligner_checkpoint(self) -> str:
        """Forced-aligner checkpoint id."""
        return self.settings.get_str('aligner_model') or 'Qwen/Qwen3-ForcedAligner-0.6B'

    @property
    def device(self) -> str:
        """The actual accelerator selected by the worker."""
        with _worker_lock:
            self._LoadWorker()
            assert self._device is not None
            return self._device

    @property
    def max_new_tokens(self) -> int:
        """Generation budget, sent on each request without reloading the model."""
        return self.settings.get_int('max_new_tokens') or 1024

    def _transcribe_chunk(self, audio_bytes : bytes, audio_format : str) -> TranscriptionResult:
        """Send a WAV path and convert the response to application data."""
        with _worker_lock:
            worker = self._LoadWorker()
            if self.aborted:
                raise SubtitleError(_("Transcription aborted"))

            chunk_path = self._WriteChunk(audio_bytes)

            try:
                response = worker.Request({
                    'type': 'transcribe', 'path': chunk_path, 'language': self.language,
                    'align': self.settings.get_bool('transcription_align', True),
                    'max_new_tokens': self.max_new_tokens,
                }, 'result', on_progress=self._report_status)
                return self.ParseResult(response, self.language)
            except WorkerError:
                worker.Abort()
                raise
            finally:
                try:
                    os.remove(chunk_path)
                except OSError:
                    pass

    @staticmethod
    def ParseResult(response : dict[str, Any], language_hint : str|None = None) -> TranscriptionResult:
        """Convert raw worker fields using the same Qwen normalization as before."""
        if not isinstance(response.get('text'), str) or not isinstance(response.get('time_stamps'), list):
            raise WorkerError(_("Malformed Qwen worker result"))

        if response.get('language') is not None and not isinstance(response['language'], str):
            raise WorkerError(_("Malformed Qwen worker language"))

        text = str(response['text'] or '').strip()
        detected = str(response['language']).strip() if response.get('language') else None

        words : list[WordTiming] = []
        for unit in response['time_stamps']:
            if not isinstance(unit, dict):
                raise WorkerError(_("Malformed Qwen worker timestamp"))

            unit_text = str(unit.get('text', '') or '').strip()
            if not unit_text:
                continue

            start = TryParseFloat(unit.get('start_time'))
            end = TryParseFloat(unit.get('end_time'))

            # Zero-length words still have a usable start.
            if start is None or end is None or end < start:
                continue

            words.append(WordTiming(text=unit_text,
                                    start=timedelta(seconds=max(0.0, start)),
                                    end=timedelta(seconds=max(0.0, end))))

        return TranscriptionResult(text=text, language=detected or language_hint, words=words)

    def _LoadWorker(self) -> WorkerHost:
        """Reuse matching models and evict the old process before loading a replacement."""
        global _loaded_key, _loaded_worker, _loaded_ready
        if self.aborted:
            raise SubtitleError(_("Transcription aborted"))

        python = ResolveEnvironmentPython(self.settings.get_str('qwen_installation_directory'), QWEN_ENVIRONMENT_NAME)
        configured = (self.settings.get_str('device') or 'auto').strip().casefold()
        allow_cpu = self.settings.get_bool('allow_cpu_fallback', False)
        key = (python, self.checkpoint, configured, self.aligner_checkpoint, allow_cpu)

        if _loaded_worker is None or not _loaded_worker.running or _loaded_key != key:
            if _loaded_worker is not None:
                # Release the old process and its device memory before loading its replacement.
                _loaded_worker.Shutdown()

            worker = WorkerHost(python, WorkerScriptPath('qwen_worker.py'))

            # Publish before loading so AbortTranscription can stop model loading too.
            self._worker = worker
            _loaded_key = None
            _loaded_worker = worker

            if self.aborted:
                worker.Abort()
                raise SubtitleError(_("Transcription aborted"))

            logging.info(_("Loading Qwen model {} in worker").format(self.checkpoint))
            ready = worker.Request({
                'type': 'load', 'checkpoint': self.checkpoint, 'aligner_checkpoint': self.aligner_checkpoint,
                'device': configured, 'allow_cpu_fallback': allow_cpu, 'max_new_tokens': self.max_new_tokens,
            }, 'ready', on_progress=self._report_status)

            if not isinstance(ready.get('device'), str) or not isinstance(ready.get('supported_languages'), list):
                worker.Abort()
                raise WorkerError(_("Malformed Qwen worker ready message"))

            _loaded_ready = ready
            _loaded_key = key

        self._worker = _loaded_worker
        self._device = _loaded_ready['device']

        # The provider resolves hints to English names, but Qwen only accepts names on its own list.
        # Keep this validation in the app and fall back to auto-detection for unsupported hints.
        language = self.settings.get_str('language')
        if language and language not in _loaded_ready['supported_languages']:
            logging.warning(_("Language '{}' is not in qwen-asr's supported list, using auto-detection").format(language))
            language = None

        self._language = language
        return _loaded_worker

    def _abort(self) -> None:
        """Interrupt an active model load or inference immediately."""
        super()._abort()
        if self._worker is not None:
            self._worker.Abort()

    def _WriteChunk(self, audio_bytes : bytes) -> str:
        """Materialize the WAV bytes only for the duration of the request."""
        handle, path = tempfile.mkstemp(suffix='.wav', prefix='subtrans-qwen-')

        with os.fdopen(handle, 'wb') as stream:
            stream.write(audio_bytes)

        return path
