"""Application-side MOSS client using an isolated, reusable model worker."""

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
from PySubtrans.Transcription.Torch.MossRuntime import MOSS_ENVIRONMENT_NAME, MOSS_MODEL, MOSS_MODEL_REVISION
from PySubtrans.Transcription.TranscriptionClient import TranscriptionClient
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionResult, TranscriptionSegment
from PySubtrans.Transcription.WorkerHost import WorkerError, WorkerHost, WorkerScriptPath

# Clients are recreated between runs, but loading the model takes seconds and several GB of device memory.
# Keep the worker at module level so the session reuses one model.
# Retain only the most recent load configuration to bound device memory use.
# The lock covers an entire chunk.
# Abort deliberately bypasses it so cancellation can interrupt a blocked inference request.
_worker_lock = RLock()
_loaded_key : tuple[str, str, bool]|None = None
_loaded_worker : WorkerHost|None = None
_loaded_device : str|None = None


class MossLocalClient(TranscriptionClient):
    """Transcribe temporary WAV chunks with the MOSS environment's Python.

    MOSS returns short segments with speaker labels and no word timings.
    Each segment becomes a chunk-relative part.
    """

    def __init__(self, settings : SettingsType):
        super().__init__(settings)
        self._worker : WorkerHost|None = None

    @property
    def language(self) -> str|None:
        """MOSS's prompt is fixed and takes no language hint."""
        return None

    @property
    def supports_timestamps(self) -> bool:
        """Segments carry start and end times."""
        return True

    @property
    def supports_diarization(self) -> bool:
        """Speaker labels are kept unless diarization is turned off."""
        return self.diarize

    @property
    def diarize(self) -> bool:
        """Whether speaker labels are kept."""
        return self.settings.get_bool('diarize', True)

    @property
    def max_new_tokens(self) -> int:
        """Generation budget, sent on each request without reloading the model."""
        return self.settings.get_int('max_new_tokens') or 32768

    @property
    def device(self) -> str:
        """The actual accelerator selected by the worker."""
        with _worker_lock:
            self._LoadWorker()
            assert _loaded_device is not None
            return _loaded_device

    def _transcribe_chunk(self, audio_bytes : bytes, audio_format : str) -> TranscriptionResult:
        """Send a WAV path and convert the response to application data."""
        with _worker_lock:
            worker = self._LoadWorker()
            if self.aborted:
                raise SubtitleError(_("Transcription aborted"))

            chunk_path = self._WriteChunk(audio_bytes)
            diarize = self.diarize

            def on_segment(message : dict[str, Any]) -> None:
                part = self.ParseSegment(message.get('segment'), diarize)
                if part is not None:
                    self._report_part(part)

            try:
                response = worker.Request({
                    'type': 'transcribe', 'path': chunk_path, 'max_new_tokens': self.max_new_tokens,
                }, 'result', on_segment)
            except WorkerError:
                worker.Abort()
                raise
            finally:
                try:
                    os.remove(chunk_path)
                except OSError:
                    pass

        if response.get('stopped_at_limit') is True:
            logging.warning(_("MOSS stopped at its limit of {} new tokens, so the end of this chunk may be missing. Use shorter chunks or raise max_new_tokens.").format(self.max_new_tokens))

        return self.ParseResult(response, self.diarize)

    @staticmethod
    def ParseResult(response : dict[str, Any], diarize : bool = True) -> TranscriptionResult:
        """Convert the worker's segments to chunk-relative parts, in the order MOSS emitted them."""
        segments = response.get('segments')
        if not isinstance(segments, list):
            raise WorkerError(_("Malformed MOSS worker result"))

        parts = [part for segment in segments if (part := MossLocalClient.ParseSegment(segment, diarize)) is not None]

        text = '\n'.join(part.text for part in parts)
        return TranscriptionResult(text=text, parts=parts)

    @staticmethod
    def ParseSegment(segment : Any, diarize : bool = True) -> TranscriptionSegment|None:
        """Convert one worker segment to a chunk-relative part, or None if it has no usable text or timing."""
        if not isinstance(segment, dict):
            raise WorkerError(_("Malformed MOSS worker segment"))

        text = str(segment.get('text') or '').strip()
        start = TryParseFloat(segment.get('start'))
        end = TryParseFloat(segment.get('end'))
        if not text or start is None or end is None or end < start:
            return None

        speaker = segment.get('speaker') if diarize else None
        return TranscriptionSegment(
            start=timedelta(seconds=max(0.0, start)), end=timedelta(seconds=max(0.0, end)),
            text=text, speaker=str(speaker) if speaker else None)

    def _LoadWorker(self) -> WorkerHost:
        """Reuse a matching model and evict the old process before loading a replacement."""
        global _loaded_key, _loaded_worker, _loaded_device
        if self.aborted:
            raise SubtitleError(_("Transcription aborted"))

        python = ResolveEnvironmentPython(self.settings.get_str('moss_installation_directory'), MOSS_ENVIRONMENT_NAME)
        configured = (self.settings.get_str('device') or 'auto').strip().casefold()
        allow_cpu = self.settings.get_bool('allow_cpu_fallback', False)
        key = (python, configured, allow_cpu)

        if _loaded_worker is None or not _loaded_worker.running or _loaded_key != key:
            if _loaded_worker is not None:
                # Release the old process and its device memory before loading its replacement.
                _loaded_worker.Shutdown()

            worker = WorkerHost(python, WorkerScriptPath('moss_worker.py'))

            # Publish before loading so AbortTranscription can stop model loading too.
            self._worker = worker
            _loaded_key = None
            _loaded_worker = worker

            if self.aborted:
                worker.Abort()
                raise SubtitleError(_("Transcription aborted"))

            logging.info(_("Loading MOSS model {} in worker").format(MOSS_MODEL))
            ready = worker.Request({
                'type': 'load', 'model': MOSS_MODEL, 'revision': MOSS_MODEL_REVISION,
                'device': configured, 'allow_cpu_fallback': allow_cpu,
            }, 'ready')

            if not isinstance(ready.get('device'), str):
                worker.Abort()
                raise WorkerError(_("Malformed MOSS worker ready message"))

            _loaded_device = ready['device']
            _loaded_key = key

        self._worker = _loaded_worker
        return _loaded_worker

    def _abort(self) -> None:
        """Interrupt an active model load or inference immediately."""
        super()._abort()
        if self._worker is not None:
            self._worker.Abort()

    def _WriteChunk(self, audio_bytes : bytes) -> str:
        """Materialize the WAV bytes only for the duration of the request."""
        handle, path = tempfile.mkstemp(suffix='.wav', prefix='subtrans-moss-')

        with os.fdopen(handle, 'wb') as stream:
            stream.write(audio_bytes)

        return path
