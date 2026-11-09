import logging
import os
import sys
from pathlib import Path

from PySubtrans.Helpers.Localization import _
from PySubtrans.Options import env_float, env_int
from PySubtrans.SettingsType import GuiSettingsType, SettingsType
from PySubtrans.Transcription.AudioChunker import DEFAULT_LOOKAHEAD_SECONDS
from PySubtrans.Transcription.Providers.Clients.MossLocalClient import MossLocalClient
from PySubtrans.Transcription.Torch.Discovery import ApplicationRoot
from PySubtrans.Transcription.Torch.MossRuntime import (
    HasMossRuntime,
    MOSS_ENVIRONMENT_NAME,
    MOSS_MAX_CHUNK_SECONDS,
    MOSS_MODEL,
)
from PySubtrans.Transcription.TranscriptionClient import TranscriptionClient
from PySubtrans.Transcription.TranscriptionProvider import OptionsScope, TranscriptionProvider

try:
    class MossLocalProvider(TranscriptionProvider):
        """
        Local transcription and diarization with MOSS-Transcribe-Diarize.

        MOSS runs in its own environment, since it needs a different Transformers major version from Qwen.
        Source installs default to the envmoss folder beside the application.
        Segments come back with speaker labels and no word timings.
        """
        name = "MOSS Local"

        information = _("""
        <p>Transcribe audio on your local machine with MOSS-Transcribe-Diarize, which also identifies speakers.</p>
        <p>The first transcription downloads model weights (~2 GB) to the Hugging Face cache.
        Subsequent runs reuse the cached files.</p>
        <p>MOSS returns short timed segments, without word timings.</p>
        """)

        def __init__(self, settings : SettingsType):
            super().__init__(self.name, settings)
            self.settings = SettingsType(self.settings | {
                'model': MOSS_MODEL,
                'device': settings.get_str('device', os.getenv('MOSS_LOCAL_DEVICE', 'auto')),
                'diarize': settings.get_bool('diarize', True),
                'max_new_tokens': settings.get_int('max_new_tokens', env_int('MOSS_MAX_NEW_TOKENS', 32768)),
                # Long chunks keep speaker labels consistent for longer, with headroom below the model's context limit.
                # Cuts already favour pauses near the maximum, so the minimum only rules out very short chunks.
                'min_chunk_seconds': settings.get_float('min_chunk_seconds', 60.0),
                'max_chunk_seconds': settings.get_float('max_chunk_seconds', 900.0),
                'allow_cpu_fallback': settings.get_bool('allow_cpu_fallback', False),
                'moss_installation_directory': settings.get_str('moss_installation_directory', ''),
                'rate_limit': settings.get_float('rate_limit', env_float('MOSS_TRANSCRIPTION_RATE_LIMIT')),
            })

            # The model takes no language hint, so there is no language setting to offer
            self.settings.pop('language', None)

            self.refresh_when_changed = ['allow_cpu_fallback', 'moss_installation_directory', 'diarize']

        @property
        def supports_diarization(self) -> bool:
            """Speaker labels are kept unless diarization is turned off."""
            return self.settings.get_bool('diarize', True)

        def GetAvailableModels(self) -> list[str]:
            """The one model this provider runs."""
            return [MOSS_MODEL]

        def GetTranscriptionClient(self, settings : SettingsType) -> TranscriptionClient:
            """Returns a new client merging provider defaults with call settings."""
            client_settings = SettingsType(self.settings.copy())
            client_settings.update(settings)
            return MossLocalClient(client_settings)

        def GetOptions(self, settings : SettingsType, scope : OptionsScope = OptionsScope.ALL) -> GuiSettingsType:
            """Returns the configurable options for the provider.

            Until an environment with the MOSS runtime is found, only its directory is shown.
            """
            directory_option : GuiSettingsType = {
                'moss_installation_directory': (str, _("Python environment with the MOSS runtime (envmoss beside the application when empty)")),
            }

            if not self._runtime_configured(settings):
                return directory_option if scope is OptionsScope.ALL else {}

            options : GuiSettingsType = {
                'diarize': (bool, _("Identify speakers")),
            }
            options.update(self._chunk_options())

            if scope is OptionsScope.ALL:
                options.update({
                    'device': (['auto', 'cuda', 'mps', 'xpu', 'cpu'], _("Compute device for local inference")),
                    'max_new_tokens': (int, _("Generation budget per chunk (long chunks need headroom)")),
                    'allow_cpu_fallback': (bool, _("Allow emergency CPU fallback (may be slow)")),
                })
                options.update(directory_option)
                options.update(self._line_options())

            return options

        def ValidateSettings(self) -> bool:
            """An environment with the MOSS runtime is required, and chunks must fit the model's context."""
            if not self._runtime_configured(self.settings):
                self.validation_message = _("MOSS Local needs a Python environment with the MOSS runtime installed")
                return False

            # The chunker can run a chunk past the maximum to reach a pause in its lookahead
            max_chunk_seconds = self.settings.get_float('max_chunk_seconds') or 0.0
            if max_chunk_seconds + DEFAULT_LOOKAHEAD_SECONDS > MOSS_MAX_CHUNK_SECONDS:
                self.validation_message = _("MOSS Local chunks can be at most {} seconds long").format(int(MOSS_MAX_CHUNK_SECONDS - DEFAULT_LOOKAHEAD_SECONDS))
                return False

            return True

        def ResolveLanguageCode(self, language : str|None, display_language : str|None = None) -> str|None:
            """MOSS's prompt is fixed and takes no language hint, so the language is always detected."""
            return None

        def _get_provider_information(self, torch_device : str = "Unknown") -> str|None:
            """Explain how to set up the environment until one is found."""
            base = super()._get_provider_information(torch_device)
            notes : list[str] = []

            if not self._runtime_configured(self.settings):
                notes.append(_("<p><b>Setup required:</b> MOSS runs in its own Python environment. "
                               "For a source install, run <code>scripts/install_moss_runtime.py {folder}</code> "
                               "with the application's Python, or set the directory of an environment that has it.</p>").format(folder=MOSS_ENVIRONMENT_NAME))

            parts = [part for part in [base, *notes] if part]
            return "\n".join(parts) if parts else None

        def _runtime_configured(self, settings : SettingsType) -> bool:
            """Whether the configured environment, or the default one for a source install, has the MOSS runtime."""
            directory = settings.get_str('moss_installation_directory')
            if directory:
                return HasMossRuntime(Path(directory).expanduser())

            if getattr(sys, 'frozen', False):
                return False

            return HasMossRuntime(ApplicationRoot() / MOSS_ENVIRONMENT_NAME)


except Exception as e:
    logging.warning(_("MOSS Local provider could not be registered: {}").format(e))
