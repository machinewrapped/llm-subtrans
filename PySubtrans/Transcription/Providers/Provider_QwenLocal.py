import logging
import os
import sys

from PySubtrans.Helpers.Languages import LanguageName
from PySubtrans.Helpers.Localization import _
from PySubtrans.Options import env_float, env_int
from PySubtrans.SettingsType import GuiSettingsType, SettingsType
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.Transcription.Torch.Runtime import TorchConfigOption
from PySubtrans.Transcription.TranscriptionClient import TranscriptionClient
from PySubtrans.Transcription.TranscriptionProvider import OptionsScope, TranscriptionProvider
from PySubtrans.Transcription.WordAlignment import WordCoverage

_QWEN_CHECKPOINTS : list[str] = [
    'Qwen/Qwen3-ASR-1.7B',
    'Qwen/Qwen3-ASR-0.6B',
]

_ALIGNER_CHECKPOINT = 'Qwen/Qwen3-ForcedAligner-0.6B'

try:
    class QwenLocalProvider(TranscriptionProvider):
        """
        Local transcription via the qwen-asr package (optional).

        The provider always registers so it is discoverable in the frozen
        application even before torch is installed.  The actual runtime
        (torch + qwen-asr) is loaded lazily on first use; until then the
        provider info panel guides the user to configure an external Torch
        installation.

        Prefers a hardware accelerator and requires explicit consent for
        CPU inference.
        """
        name = "Qwen Local"

        information = _("""
        <p>Transcribe audio on your local machine with Qwen3-ASR.</p>
        <p>The first transcription downloads model weights (~6 GB) to the
        Hugging Face cache. Subsequent runs reuse the cached files.</p>
        """)

        aligner_models = [_ALIGNER_CHECKPOINT]

        # The forced aligner drops stretches of the transcript and crams others into a moment
        word_coverage = WordCoverage.PARTIAL

        def __init__(self, settings : SettingsType):
            super().__init__(self.name, settings)
            self.settings = SettingsType(self.settings | {
                'model': settings.get_str('model', os.getenv('QWEN_LOCAL_MODEL', _QWEN_CHECKPOINTS[0])),
                'device': settings.get_str('device', os.getenv('QWEN_LOCAL_DEVICE', 'auto')),
                'aligner_model': settings.get_str('aligner_model', os.getenv('QWEN_ALIGNER_MODEL', _ALIGNER_CHECKPOINT)),
                'max_new_tokens': settings.get_int('max_new_tokens', env_int('QWEN_MAX_NEW_TOKENS', 2048)),
                'request_timeout': settings.get_float('request_timeout', env_float('TRANSCRIPTION_TIMEOUT', 300.0)),
                'rate_limit': settings.get_float('rate_limit', env_float('QWEN_TRANSCRIPTION_RATE_LIMIT')),
                # Short chunks fit the default generation budget and GPU memory.
                # Longer chunks need a raised max_new_tokens to avoid silent truncation.
                'min_chunk_seconds': settings.get_float('min_chunk_seconds', 30.0),
                'max_chunk_seconds': settings.get_float('max_chunk_seconds', 60.0),
                'allow_cpu_fallback': settings.get_bool('allow_cpu_fallback', False),
                'torch_installation_directory': settings.get_str('torch_installation_directory', ''),
            })

            self.refresh_when_changed = ['allow_cpu_fallback', 'torch_installation_directory', 'language']

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

        def GetOptions(self, settings : SettingsType, scope : OptionsScope = OptionsScope.ALL) -> GuiSettingsType:
            """Returns the configurable options for the provider.

            Uses progressive disclosure: when torch_installation_directory is
            not configured, only the torch directory setting is shown so the
            user focuses on the critical prerequisite first.
            """
            if not settings.get_str('torch_installation_directory'):
                if scope is not OptionsScope.ALL:
                    return {}

                return {
                    'torch_installation_directory': (TorchConfigOption, _("Configure the Torch environment for local transcription")),
                }

            options : GuiSettingsType = {
                'model': (self.available_models, _("Transcription model to run")),
                'language': (str, _("Spoken language hint (optional, auto-detected when empty)")),
            }
            options.update(self._chunk_options())

            if scope is OptionsScope.ALL:
                options.update({
                    'device': (['auto', 'cuda', 'mps', 'xpu', 'cpu'], _("Compute device for local inference")),
                    'aligner_model': (self.aligner_models, _("Aligner model for word timestamps")),
                    'max_new_tokens': (int, _("Generation budget per chunk (long chunks need headroom)")),
                    'rate_limit': (float, _("Maximum requests per minute (0 for unlimited)")),
                    'allow_cpu_fallback': (bool, _("Allow emergency CPU fallback (may be slow)")),
                    'torch_installation_directory': (TorchConfigOption, _("Set up Torch...")),
                })

                options.update(self._line_options())

            return options

        def ValidateSettings(self) -> bool:
            """Torch installation directory is required for frozen builds.

            When running from source (not frozen) the active venv already
            contains torch, so a separate installation directory is not needed.
            """
            if bool(self.settings.get_str('torch_installation_directory')):
                return True

            return not getattr(sys, 'frozen', False)

        def ResolveLanguageCode(self, language : str|None, display_language : str|None = None) -> str|None:
            """qwen-asr takes English language names ("Chinese", "English"), or None to auto-detect."""
            locale = self.ResolveLanguageLocale(language, display_language)
            return LanguageName(locale) if locale is not None else None

        def _get_provider_information(self, torch_device : str = "Unknown") -> str|None:
            """Describe Torch setup and any explicitly enabled CPU fallback."""
            base = super()._get_provider_information(torch_device)
            notes : list[str] = []

            if not self.settings.get_str('torch_installation_directory'):
                notes.extend([
                    _("<p><b>Torch setup required:</b> Qwen3-ASR needs a separate PyTorch installation. The correct build depends on your operating system and hardware.</p>"),
                    _("<p>Click <b>Set up Torch...</b> to detect available hardware and install a suitable Torch build.</p>"),
                ])
            elif torch_device == "Unknown":
                notes.append(_("<p>Torch is configured but has not been verified by a transcription yet.</p>"))
                notes.append(_("<p>The first transcription will download model weights (~6 GB) to the Hugging Face cache.</p>"))
            elif "cpu" in torch_device.casefold():
                if self.settings.get_bool('allow_cpu_fallback', False):
                    notes.append(_("<p>Running on CPU: transcription will work but likely much slower than on a GPU.</p>"))
                else:
                    notes.append(_("<p>CPU inference is disabled. Enable it if you accept the performance implications.</p>"))

            parts = [part for part in [base, *notes] if part]
            return "\n".join(parts) if parts else None


except Exception as e:
    logging.warning(_("Qwen Local provider could not be registered: {}").format(e))
