import importlib.util
import logging
import os
import tempfile
from typing import Any

from PySubtrans.Helpers.Localization import _
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.Transcription.TranscriptionAligner import NormaliseAlignerLanguage
from PySubtrans.Transcription.TranscriptionClient import TranscriptionClient
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionResult
from PySubtrans.Transcription.Providers.Provider_QwenLocal import (
    _ALIGNER_CHECKPOINT,
    _QWEN_ALIGNER_LANGUAGES,
    _QWEN_CHECKPOINTS,
    parse_qwen_result,
)

# Loaded ASR models per (checkpoint, device, generation budget, aligner):
# loading takes seconds, and load-time settings only apply to fresh loads.
# No eviction: entries accumulate across settings changes within a session.
# Revisit if there are ever more than two models to choose from.
_loaded_models : dict[tuple[str, str, int, str], object] = {}


if not importlib.util.find_spec("qwen_asr"):
    logging.debug(_("qwen-asr package is not installed. Qwen local transcription will not be available"))
else:
    try:
        import torch
        from qwen_asr import Qwen3ASRModel      #type: ignore[import]

        def _mps_available() -> bool:
            """Apple Silicon GPU backend; absent on torch builds without it."""
            mps = getattr(torch.backends, 'mps', None)
            if mps is None:
                return False
            return bool(mps.is_available() and mps.is_built())


        def _xpu_available() -> bool:
            """Intel GPU backend; absent on torch builds without it."""
            xpu = getattr(torch, 'xpu', None)
            if xpu is None:
                return False
            return bool(xpu.is_available())


        class QwenLocalClient(TranscriptionClient):
            """
            In-process transcription via the official qwen-asr package.

            Requests word timestamps when the language is aligner-supported;
            otherwise returns flat text and the coordinator falls back to
            chunk-level lines. Heavy imports stay inside methods so merely
            constructing the client never touches torch.
            """
            def __init__(self, settings : SettingsType):
                super().__init__(settings)
                self._model : object|None = None

            @property
            def supports_timestamps(self) -> bool:
                """Word timings when the aligner covers the language."""
                return True

            @property
            def checkpoint(self) -> str:
                """ASR checkpoint id."""
                return self.settings.get_str('model') or _QWEN_CHECKPOINTS[0]

            @property
            def aligner_checkpoint(self) -> str:
                """Forced-aligner checkpoint id for timestamp requests."""
                return self.settings.get_str('aligner_model') or _ALIGNER_CHECKPOINT

            @property
            def device(self) -> str:
                """Compute device for both models."""
                configured = (self.settings.get_str('device') or 'auto').strip().casefold()
                if configured not in ('auto', 'cuda', 'mps', 'xpu', 'cpu'):
                    logging.warning(_("Unknown device '{}', using automatic selection").format(configured))
                    configured = 'auto'

                if configured == 'cpu':
                    return 'cpu'

                if configured in ('cuda', 'mps', 'xpu'):
                    resolved = self._resolve_device(configured)
                    if resolved is not None:
                        return resolved
                    logging.warning(_("{} unavailable, running Qwen transcription on CPU (slow)").format(configured.upper()))
                    return 'cpu'

                for candidate in ('cuda', 'mps', 'xpu'):
                    resolved = self._resolve_device(candidate)
                    if resolved is not None:
                        return resolved

                return 'cpu'

            def _resolve_device(self, candidate : str) -> str|None:
                """Resolve a device candidate without importing anything new."""
                if candidate == 'cuda':
                    # Covers NVIDIA CUDA and AMD ROCm (which exposes the CUDA API).
                    return 'cuda:0' if torch.cuda.is_available() else None
                if candidate == 'mps':
                    return 'mps' if _mps_available() else None
                if candidate == 'xpu':
                    return 'xpu:0' if _xpu_available() else None
                return None

            @property
            def inference_dtype(self) -> Any:
                """Torch dtype matching the resolved device (MPS lacks bfloat16)."""
                device = self.device
                if device.startswith('mps') or device.startswith('xpu'):
                    return torch.float16
                return torch.bfloat16

            @property
            def max_new_tokens(self) -> int:
                """Generation budget per chunk (long chunks need headroom)."""
                return self.settings.get_int('max_new_tokens') or 1024

            # Transcription

            def _transcribe_chunk(self, audio_bytes : bytes, audio_format : str, language : str|None) -> TranscriptionResult:
                model = self._load_model()
                chunk_path = self._write_chunk(audio_bytes)
                canonical = NormaliseAlignerLanguage(language, _QWEN_ALIGNER_LANGUAGES)
                # Qwen can detect the language and pass it to its forced aligner
                # when no hint is supplied.  Keep the default timestamp request
                # enabled for auto-detection; unsupported detected languages are
                # represented by the SDK without word timings.
                want_stamps = self.settings.get_bool('transcription_align', True)

                try:
                    try:
                        results = model.transcribe(
                            audio=chunk_path,
                            language=canonical,
                            return_time_stamps=want_stamps,
                        )
                    except ValueError as e:
                        # The ASR model may detect a language outside the
                        # forced aligner's coverage. Preserve the transcript
                        # and report it without timings in that case.
                        message = str(e).casefold()
                        unsupported = 'unsupported language' in message or 'language is not supported' in message

                        if not (want_stamps and unsupported):
                            raise

                        results = model.transcribe(
                            audio=chunk_path,
                            language=canonical,
                            return_time_stamps=False,
                        )
                except Exception as e:
                    raise SubtitleError(_("Qwen transcription failed: {}").format(str(e)), error=e)
                finally:
                    try:
                        os.remove(chunk_path)
                    except OSError:
                        pass

                if not results:
                    # Empty results (silence, music) are expected, not errors
                    return TranscriptionResult(text="", language=language)

                text, detected, words = parse_qwen_result(results[0])
                return TranscriptionResult(text=text, language=detected or language, words=words)

            def _load_model(self) -> Any:
                if self._model is not None:
                    return self._model

                cache_key = (self.checkpoint, self.device, self.max_new_tokens, self.aligner_checkpoint)
                cached = _loaded_models.get(cache_key)
                if cached is not None:
                    self._model = cached
                    return cached

                logging.info(_("Loading Qwen model {} on {}").format(self.checkpoint, self.device))

                try:
                    dtype = self.inference_dtype
                    model = Qwen3ASRModel.from_pretrained(
                        self.checkpoint,
                        dtype=dtype,
                        device_map=self.device,
                        max_new_tokens=self.max_new_tokens,
                        forced_aligner=self.aligner_checkpoint,
                        forced_aligner_kwargs=dict(dtype=dtype, device_map=self.device),
                    )
                except Exception as e:
                    raise SubtitleError(_("Unable to load Qwen model: {}").format(str(e)), error=e)

                _loaded_models[cache_key] = model
                self._model = model
                return model

            def _write_chunk(self, audio_bytes : bytes) -> str:
                handle, path = tempfile.mkstemp(suffix='.wav', prefix='subtrans-qwen-')

                with os.fdopen(handle, 'wb') as f:
                    f.write(audio_bytes)
                return path

    except ImportError as e:
        logging.debug(_("qwen-asr dependencies missing, Qwen Local provider unavailable ({})").format(e))
