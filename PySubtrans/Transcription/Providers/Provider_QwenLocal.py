import importlib.util
import logging
import os
from datetime import timedelta

from PySubtrans.Helpers.Languages import LanguageName
from PySubtrans.Helpers.Localization import _
from PySubtrans.Helpers.Parse import TryParseFloat
from PySubtrans.Options import env_float, env_int
from PySubtrans.SettingsType import GuiSettingsType, SettingsType
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.Transcription.WordTiming import WordTiming
from PySubtrans.Transcription.TranscriptionClient import TranscriptionClient
from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider

_QWEN_CHECKPOINTS : list[str] = [
    'Qwen/Qwen3-ASR-1.7B',
    'Qwen/Qwen3-ASR-0.6B',
]

_ALIGNER_CHECKPOINT = 'Qwen/Qwen3-ForcedAligner-0.6B'


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

    words.sort(key=lambda w: w.start)
    return text, language, words


if not importlib.util.find_spec("qwen_asr"):
    logging.debug(_("qwen-asr package is not installed. Qwen Local provider will not be available"))
else:
    try:
        class QwenLocalProvider(TranscriptionProvider):
            """
            Local transcription via the qwen-asr package (optional).

            Requires a GPU-enabled torch install (CUDA on NVIDIA, MPS on Apple Silicon).
            """
            name = "Qwen Local"

            information = _("""
            <p>Transcribe audio on your local machine with Qwen3-ASR.</p>
            """)

            def _get_provider_information(self, torch_device : str = "Unknown") -> str|None:
                """Append torch install guidance until a run records a device."""
                base = super()._get_provider_information(torch_device)
                if torch_device == "Unknown":
                    note = _("<p>Needs a working torch install (<a href=\"https://pytorch.org/get-started/locally/\">pytorch.org</a>); ")
                elif "cpu" in torch_device.casefold():
                    note = _("<p>Running on CPU: transcription will work but much slower than on a GPU.</p>")
                else:
                    note = None

                return f"{base}\n{note}" if base else note

            # Device and budgets rarely change per job; model and language do
            advanced_settings = ['device', 'aligner_model', 'max_new_tokens', 'rate_limit']

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
                # Sanctioned lazy import: the client module pulls torch and
                # qwen_asr (~10s), so it loads on first use, not on registration.
                try:
                    from PySubtrans.Transcription.Providers.Clients.QwenLocalClient import QwenLocalClient
                except ImportError as e:
                    raise SubtitleError(_("Qwen transcription runtime is not installed"), error=e)
                client_settings = SettingsType(self.settings.copy())
                client_settings.update(settings)
                return QwenLocalClient(client_settings)

            def GetOptions(self, settings : SettingsType) -> GuiSettingsType:
                """Returns the configurable options for the provider."""
                return {
                    'model': (self.available_models, _("ASR checkpoint to run locally")),
                    'language': (str, _("Spoken language hint, e.g. Chinese or English (optional, auto-detected when empty)")),
                    'device': (['auto', 'cuda', 'mps', 'xpu', 'cpu'], _("Compute device for local inference (auto prefers CUDA, then MPS, then XPU)")),
                    'aligner_model': (str, _("Forced-aligner checkpoint for word timestamps")),
                    'max_new_tokens': (int, _("Generation budget per chunk (long chunks need headroom)")),
                    'rate_limit': (float, _("Maximum requests per minute (0 for unlimited; local inference is unmetered)")),
                }

            def ResolveLanguageCode(self, language : str|None, display_language : str|None = None) -> str|None:
                """qwen-asr takes English language names ("Chinese", "English"), or None to auto-detect."""
                locale = self.ResolveLanguageLocale(language, display_language)
                return LanguageName(locale) if locale is not None else None

    except ImportError as e:
        logging.debug(_("qwen-asr dependencies missing, Qwen Local provider unavailable ({})").format(e))
