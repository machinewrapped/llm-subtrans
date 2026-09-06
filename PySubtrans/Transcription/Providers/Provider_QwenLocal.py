import importlib.util
import logging
import os
import tempfile
from datetime import timedelta
from typing import Any

from PySubtrans.Helpers.Localization import _
from PySubtrans.Options import SettingsType, env_float, env_int
from PySubtrans.SettingsType import GuiSettingsType, SettingsType
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.Transcription.TranscriptionAligner import WordTiming
from PySubtrans.Transcription.TranscriptionClient import TranscriptionClient
from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionResult

# Canonical ASR languages for the Qwen3-ASR family
_QWEN_ASR_LANGUAGES : list[str] = [
    'Chinese', 'English', 'Cantonese', 'Arabic', 'German', 'French',
    'Spanish', 'Portuguese', 'Indonesian', 'Italian', 'Korean',
    'Russian', 'Thai', 'Vietnamese', 'Japanese', 'Turkish', 'Hindi',
    'Malay', 'Dutch', 'Swedish', 'Danish', 'Finnish', 'Polish',
    'Czech', 'Filipino', 'Persian', 'Greek', 'Hungarian', 'Macedonian',
    'Romanian',
]

# Aligner subset gating timestamp requests (11 published languages)
_QWEN_ALIGNER_LANGUAGES : list[str] = [
    'Chinese', 'English', 'Cantonese', 'French', 'German', 'Italian',
    'Japanese', 'Korean', 'Portuguese', 'Russian', 'Spanish',
]

_QWEN_CHECKPOINTS : list[str] = [
    'Qwen/Qwen3-ASR-1.7B',
    'Qwen/Qwen3-ASR-0.6B',
]

_ALIGNER_CHECKPOINT = 'Qwen/Qwen3-ForcedAligner-0.6B'

# Loaded ASR models per (checkpoint, device, generation budget, aligner):
# loading takes seconds, and load-time settings only apply to fresh loads
_loaded_models : dict[tuple[str, str, int, str], object] = {}


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
        try:
            start = max(0.0, float(getattr(unit, 'start_time', 0.0) or 0.0))
            end = max(0.0, float(getattr(unit, 'end_time', 0.0) or 0.0))
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        words.append(WordTiming(text=unit_text,
                                start=timedelta(seconds=start),
                                end=timedelta(seconds=end)))

    words.sort(key=lambda w: w.start)
    return text, language, words


if not importlib.util.find_spec("qwen_asr"):
    logging.debug(_("qwen-asr package is not installed. Qwen Local provider will not be available"))
else:
    try:
        import torch
        from qwen_asr import Qwen3ASRModel

        from PySubtrans.Transcription.TranscriptionAligner import NormaliseAlignerLanguage


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
                if configured not in ('auto', 'cuda', 'cpu'):
                    logging.warning(_("Unknown device '{}', using automatic selection").format(configured))
                    configured = 'auto'

                if configured == 'cpu':
                    return 'cpu'

                if torch.cuda.is_available():
                    return 'cuda:0'

                if configured == 'cuda':
                    logging.warning(_("CUDA unavailable, running Qwen transcription on CPU (slow)"))

                return 'cpu'

            @property
            def max_new_tokens(self) -> int:
                """Generation budget per chunk (long chunks need headroom)."""
                return self.settings.get_int('max_new_tokens') or 1024

            def _transcribe_chunk(self, audio_bytes : bytes, audio_format : str, language : str|None) -> TranscriptionResult:
                model = self._load_model()
                chunk_path = self._write_chunk(audio_bytes)
                canonical = NormaliseAlignerLanguage(language, _QWEN_ALIGNER_LANGUAGES)
                want_stamps = self.settings.get_bool('transcription_align', True) and canonical is not None

                try:
                    results = model.transcribe(
                        audio=chunk_path,
                        language=canonical,
                        return_time_stamps=want_stamps,
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
                    model = Qwen3ASRModel.from_pretrained(
                        self.checkpoint,
                        dtype=torch.bfloat16,
                        device_map=self.device,
                        max_new_tokens=self.max_new_tokens,
                        forced_aligner=self.aligner_checkpoint,
                        forced_aligner_kwargs=dict(dtype=torch.bfloat16, device_map=self.device),
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


        class QwenLocalProvider(TranscriptionProvider):
            """
            Local transcription via the official qwen-asr package (optional).

            Only registered when qwen-asr is installed; see the
            `transcription` packaging extra (torch with CUDA comes from
            pytorch.org separately).
            """
            name = "Qwen Local"

            information = """
            <p>Transcribe locally with the official qwen-asr package (Qwen3-ASR).</p>
            <p>Requires the <tt>transcription</tt> extra and a CUDA torch install. No API key needed.</p>
            """

            @property
            def recommended_min_chunk_seconds(self) -> float:
                """Short chunks fit the default generation budget and GPU memory."""
                return 8.0

            @property
            def recommended_max_chunk_seconds(self) -> float:
                """Longer chunks need a raised max_new_tokens to avoid silent truncation."""
                return 60.0

            def __init__(self, settings : SettingsType):
                super().__init__(self.name, SettingsType({
                    'model': settings.get_str('model', os.getenv('QWEN_LOCAL_MODEL', _QWEN_CHECKPOINTS[0])),
                    'language': settings.get_str('language', os.getenv('TRANSCRIPTION_LANGUAGE')),
                    'device': settings.get_str('device', os.getenv('QWEN_LOCAL_DEVICE', 'auto')),
                    'aligner_model': settings.get_str('aligner_model', os.getenv('QWEN_ALIGNER_MODEL', _ALIGNER_CHECKPOINT)),
                    'max_new_tokens': settings.get_int('max_new_tokens', env_int('QWEN_MAX_NEW_TOKENS', 1024)),
                    'request_timeout': settings.get_float('request_timeout', env_float('TRANSCRIPTION_TIMEOUT', 300.0)),
                    'rate_limit': settings.get_float('rate_limit', env_float('QWEN_TRANSCRIPTION_RATE_LIMIT')),
                }))

            def GetAvailableModels(self) -> list[str]:
                """ASR checkpoints served by this provider."""
                return list(_QWEN_CHECKPOINTS)

            def GetTranscriptionClient(self, settings : SettingsType) -> TranscriptionClient:
                """Returns a new client merging provider defaults with call settings."""
                client_settings = SettingsType(self.settings.copy())
                client_settings.update(settings)
                return QwenLocalClient(client_settings)

            def GetOptions(self, settings : SettingsType) -> GuiSettingsType:
                """Returns the configurable options for the provider."""
                return {
                    'model': (self.available_models, _("ASR checkpoint to run locally")),
                    'language': (str, _("Spoken language hint, e.g. Chinese or English (optional, auto-detected when empty)")),
                    'device': (['auto', 'cuda', 'cpu'], _("Compute device for local inference")),
                    'aligner_model': (str, _("Forced-aligner checkpoint for word timestamps")),
                    'max_new_tokens': (int, _("Generation budget per chunk (long chunks need headroom)")),
                    'rate_limit': (float, _("Maximum requests per minute (0 for unlimited; local inference is unmetered)")),
                }

    except ImportError as e:
        logging.debug(_("qwen-asr dependencies missing, Qwen Local provider unavailable ({})").format(e))
