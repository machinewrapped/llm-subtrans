from datetime import timedelta
import gc
import importlib
import importlib.util
import logging
import os
import tempfile
from typing import Any

from PySubtrans.Helpers.ImportGuard import UsingOriginalImport
from PySubtrans.Helpers.Localization import _
from PySubtrans.Helpers.Parse import TryParseFloat
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.Transcription.TranscriptionClient import TranscriptionClient
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionResult
from PySubtrans.Transcription.Torch.QwenRuntime import QWEN_ASR_MODULE
from PySubtrans.Transcription.Torch.Runtime import PrepareTorchRuntime, TorchConfigOption
from PySubtrans.Transcription.Providers.Provider_QwenLocal import (
    _ALIGNER_CHECKPOINT,
    _QWEN_CHECKPOINTS,
)
from PySubtrans.Transcription.WordTiming import WordTiming

# A single loaded ASR model (plus aligner) is kept for the session, keyed by (checkpoint, device, aligner).
# Loading takes seconds, but each model set is several GB of device memory,
# so a settings change releases the old one before loading its replacement.
_loaded_key : tuple[str, str, str]|None = None
_loaded_model : object|None = None


torch : Any|None = None
Qwen3ASRModel : Any|None = None
_QWEN_SUPPORTED_LANGUAGES : list[str] = []


def _load_qwen_dependencies(settings: SettingsType) -> None:
    """Configure and import the optional Qwen runtime on first client use."""
    global torch, Qwen3ASRModel, _QWEN_SUPPORTED_LANGUAGES

    logging.info(_("Preparing Torch runtime..."))
    PrepareTorchRuntime(settings.get_str('torch_installation_directory', ''))
    if torch is not None and Qwen3ASRModel is not None:
        return

    # Packaged builds do not bundle qwen-asr, so environments set up for earlier versions may have Torch alone
    if importlib.util.find_spec(QWEN_ASR_MODULE) is None:
        raise ImportError(_("The Torch environment does not include the Qwen runtime. Use {button} and select the same environment to install it.").format(button=TorchConfigOption.label))

    try:
        logging.info(_("Importing torch..."))
        torch = importlib.import_module("torch")

        logging.info(_("Importing qwen_asr (this can take a while on first run)..."))
        # qwen_asr pulls in transformers, which pulls in pandas for the first time.
        # If PySide6 has already replaced builtins.__import__ (it does this as soon as it is imported, to support `from __feature__ import ...`), that replacement corrupts six's synthetic module machinery partway through pandas' own import chain.
        # Importing under the pre-PySide6 import function avoids it; a no-op outside the GUI, where nothing patched __import__.
        with UsingOriginalImport():
            qwen_module = importlib.import_module("qwen_asr")
            Qwen3ASRModel = getattr(qwen_module, "Qwen3ASRModel")

            logging.info(_("Importing qwen_asr.inference.utils..."))
            utils_module = importlib.import_module("qwen_asr.inference.utils")
            _QWEN_SUPPORTED_LANGUAGES = list(getattr(utils_module, "SUPPORTED_LANGUAGES"))

        logging.info(_("Qwen runtime imports complete"))
    except (ImportError, OSError, AttributeError) as error:
        torch = None
        Qwen3ASRModel = None
        raise ImportError(_("Qwen transcription runtime could not be loaded: {}. Restart after changing the Torch installation setting.").format(error)) from error


def _mps_available() -> bool:
    """Apple Silicon GPU backend; absent on torch builds without it."""
    if torch is None:
        return False
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


class _SpaceSplitKoreanTokenizer:
    """
    Stands in for soynlp's Korean tokenizer in qwen-asr's forced aligner when soynlp is not installed.
    Local transcription setup installs soynlp, but an environment prepared by hand may lack it.
    Korean separates words with spaces, so splitting on them still aligns words, at a coarser grain.
    """
    def __init__(self):
        self._warned = False

    def tokenize(self, text : str) -> list[str]:
        """Split on whitespace, warning the first time that Korean timestamps are less precise."""
        if not self._warned:
            self._warned = True
            logging.warning(_("Korean word timestamps need the soynlp package, which is not installed in the Torch environment. "
                              "Aligning Korean text on spaces instead, so timestamps are less precise."))
        return text.split()


def _install_korean_tokenizer_fallback(model : Any) -> None:
    """Give qwen-asr's forced aligner a Korean tokenizer when soynlp is not installed, so Korean audio can still be aligned."""
    if importlib.util.find_spec('soynlp') is not None:
        return

    # The aligner only imports soynlp when ko_tokenizer is unset
    processor = getattr(getattr(model, 'forced_aligner', None), 'aligner_processor', None)
    if processor is not None and hasattr(processor, 'ko_tokenizer') and processor.ko_tokenizer is None:
        processor.ko_tokenizer = _SpaceSplitKoreanTokenizer()


class QwenLocalClient(TranscriptionClient):
    """
    In-process transcription via the official qwen-asr package.

    Requests word timestamps when the language is aligner-supported;
    otherwise returns flat text and the coordinator falls back to chunk-level lines.
    Device resolution and model loading are deferred until the first chunk, so constructing the client is cheap.
    """
    def __init__(self, settings : SettingsType):
        super().__init__(settings)
        try:
            _load_qwen_dependencies(self.settings)
        except (ImportError, OSError, AttributeError) as error:
            raise SubtitleError(_(
                "Qwen transcription runtime could not be loaded. Check that the configured "
                "external Torch installation is compatible with this application, then "
                "restart after changing the Torch installation setting. Details: {}"
            ).format(error), error=error) from error
        self._model : object|None = None
        self._device : str|None = None

        # The provider resolves hints to English names; qwen-asr only accepts names on its list,
        # so decide once whether to use the hint or fall back to auto-detect.
        language = self.settings.get_str('language')
        if language and language not in _QWEN_SUPPORTED_LANGUAGES:
            logging.warning(_("Language '{}' is not in qwen-asr's supported list, using auto-detection").format(language))
            language = None
        self._language : str|None = language

    @property
    def language(self) -> str|None:
        """Hint validated against qwen-asr's supported list at construction, or None to auto-detect."""
        return self._language

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
        """Compute device for both models, resolved once so availability warnings are not repeated."""
        if self._device is None:
            self._device = self._select_device()
        return self._device

    def _select_device(self) -> str:
        """Map the configured device setting onto an available torch device."""
        configured = (self.settings.get_str('device') or 'auto').strip().casefold()
        allow_cpu_fallback = self.settings.get_bool('allow_cpu_fallback', False)
        if configured not in ('auto', 'cuda', 'mps', 'xpu', 'cpu'):
            logging.warning(_("Unknown device '{}', using automatic selection").format(configured))
            configured = 'auto'

        if configured == 'cpu':
            if not allow_cpu_fallback:
                raise SubtitleError(_("CPU inference is disabled. Enable 'allow_cpu_fallback' in Qwen Local advanced settings to give consent for this emergency fallback."))
            return 'cpu'

        if configured in ('cuda', 'mps', 'xpu'):
            resolved = self._resolve_device(configured)
            if resolved is not None:
                return resolved
            if allow_cpu_fallback:
                return 'cpu'
            raise SubtitleError(_("The configured {} accelerator is unavailable. Enable 'allow_cpu_fallback' in Qwen Local advanced settings to permit CPU fallback, or choose an available accelerator.").format(configured.upper()))

        for candidate in ('cuda', 'mps', 'xpu'):
            resolved = self._resolve_device(candidate)
            if resolved is not None:
                return resolved

        if allow_cpu_fallback:
            return 'cpu'
        raise SubtitleError(_("No supported hardware accelerator is available. Enable 'allow_cpu_fallback' in Qwen Local advanced settings to permit CPU inference."))

    def _resolve_device(self, candidate : str) -> str|None:
        """Resolve a device candidate without importing anything new."""
        assert torch is not None  # invariant: torch loaded in __init__ via _load_qwen_dependencies
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
        assert torch is not None  # invariant: torch loaded in __init__ via _load_qwen_dependencies
        device = self.device
        if device.startswith('mps') or device.startswith('xpu'):
            return torch.float16
        return torch.bfloat16

    @property
    def max_new_tokens(self) -> int:
        """Generation budget per chunk (long chunks need headroom)."""
        return self.settings.get_int('max_new_tokens') or 1024

    # Transcription

    def _transcribe_chunk(self, audio_bytes : bytes, audio_format : str) -> TranscriptionResult:
        model = self._load_model()
        # The budget is read at generation time, so a changed setting applies to a reused model
        model.max_new_tokens = self.max_new_tokens
        chunk_path = self._write_chunk(audio_bytes)
        # Qwen can detect the language and pass it to its forced aligner when no hint is supplied,
        # so timestamps are requested by default even when auto-detecting.
        want_stamps = self.settings.get_bool('transcription_align', True)

        try:
            try:
                results = model.transcribe(
                    audio=chunk_path,
                    language=self.language,
                    return_time_stamps=want_stamps,
                )
            except ValueError as e:
                # The ASR model may detect a language outside the forced aligner's coverage.
                # Try English alignment first (better than nothing), then fall back to
                # no timestamps if that also fails.
                message = str(e).casefold()
                unsupported = 'unsupported language' in message or 'language is not supported' in message

                if not (want_stamps and unsupported):
                    raise

                logging.warning(_("Detected language unsupported by aligner, retrying with English"))
                try:
                    results = model.transcribe(
                        audio=chunk_path,
                        language='English',
                        return_time_stamps=True,
                    )
                except ValueError:
                    logging.warning(_("Alignment failed, timestamps will be approximate"))
                    results = model.transcribe(
                        audio=chunk_path,
                        language=self.language,
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
            return TranscriptionResult(text="", language=self.language)

        text, detected, words = parse_qwen_result(results[0])
        return TranscriptionResult(text=text, language=detected or self.language, words=words)

    def _load_model(self) -> Any:
        global _loaded_key, _loaded_model

        if self._model is not None:
            return self._model

        cache_key = (self.checkpoint, self.device, self.aligner_checkpoint)
        if _loaded_model is not None:
            if _loaded_key == cache_key:
                self._model = _loaded_model
                return _loaded_model

            self._release_loaded_model()

        logging.info(_("Loading Qwen model {} on {}").format(self.checkpoint, self.device))

        assert Qwen3ASRModel is not None  # invariant: loaded in __init__ via _load_qwen_dependencies

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

        _install_korean_tokenizer_fallback(model)

        _loaded_key = cache_key
        _loaded_model = model
        self._model = model
        return model

    def _release_loaded_model(self) -> None:
        """Drop the session's cached model and return its device memory before loading another."""
        global _loaded_key, _loaded_model

        logging.info(_("Releasing previously loaded Qwen model {}").format(_loaded_key[0] if _loaded_key else ""))

        _loaded_key = None
        _loaded_model = None
        gc.collect()

        if torch is not None:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            elif _mps_available():
                torch.mps.empty_cache()

    def _write_chunk(self, audio_bytes : bytes) -> str:
        handle, path = tempfile.mkstemp(suffix='.wav', prefix='subtrans-qwen-')

        with os.fdopen(handle, 'wb') as f:
            f.write(audio_bytes)
        return path

def parse_qwen_result(result : object) -> tuple[str, str|None, list[WordTiming]]:
    """
    Extract (text, language, word timings) from a qwen-asr result.

    Pure function over the result shape so it is unit-testable without
    torch installed.
    """
    text = str(getattr(result, 'text', '') or '').strip()
    language = getattr(result, 'language', None)
    language = str(language).strip() if language else None

    words : list[WordTiming] = []
    for unit in getattr(result, 'time_stamps', None) or []:
        unit_text = str(getattr(unit, 'text', '') or '').strip()
        if not unit_text:
            continue
        start = TryParseFloat(getattr(unit, 'start_time', None))
        end = TryParseFloat(getattr(unit, 'end_time', None))
        if start is None or end is None or end <= start:
            continue
        words.append(WordTiming(text=unit_text,
                                start=timedelta(seconds=max(0.0, start)),
                                end=timedelta(seconds=max(0.0, end))))

    return text, language, words


