from __future__ import annotations

import html
import logging
from typing import cast

from babel import Locale

from PySubtrans.Helpers.Languages import ResolveLanguage
from PySubtrans.Helpers.Localization import _
from PySubtrans.Options import Options
from PySubtrans.SettingsType import GuiSettingsType, SettingsType
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.Transcription.TranscriptionClient import TranscriptionClient


class TranscriptionProvider:
    """
    Base class for transcription service providers.

    Mirrors TranslationProvider but stays a separate hierarchy on purpose:
    transcription model catalogs, options and capability flags are disjoint
    from translation ones. API keys are shared at the Options level instead
    (see ResolveProviderSettings).
    """
    # Settings hidden from the Transcribe dialog (stable choices that belong
    # in Settings): the dialog shows the rest for per-run tweaks.
    advanced_settings : list[str] = []

    # Optional no-key walkthrough; keyed providers define information_noapikey
    information_noapikey : str|None = None

    def __init__(self, name : str, settings : SettingsType):
        self.name : str = name
        self.settings : SettingsType = settings
        self._available_models : list[str] = []
        self.refresh_when_changed : list[str] = []
        self.validation_message : str|None = None

    @classmethod
    def ResolveProviderSettings(cls, provider_name : str, settings : SettingsType,
                                provider_settings : SettingsType|None = None) -> SettingsType:
        """
        Merge settings with shared credentials from the provider_settings dict.

        Only credentials travel across capabilities (api_key, proxy): endpoint
        conventions differ per capability (translation and transcription use
        different base paths), so server addresses and models are never
        shared. Transcription settings live under "<name> Transcription".
        """
        resolved = SettingsType(settings or {})
        if provider_settings is not None:
            # Transcription-specific settings fill gaps; explicit settings win.
            own = provider_settings.get_dict(cls.SettingsKey(provider_name))
            if own:
                resolved = SettingsType(own | resolved)

            # Only credentials travel across capabilities, never endpoints.
            shared = provider_settings.get_dict(provider_name)
            for key in ('api_key', 'proxy'):
                if not resolved.get(key) and shared.get(key):
                    resolved[key] = shared.get(key)

        return resolved

    @staticmethod
    def SettingsKey(provider_name : str) -> str:
        """
        Settings namespace for a transcription provider, kept separate
        from its translation counterpart (see ResolveProviderSettings).
        """
        return f"{provider_name} Transcription"

    @property
    def available_models(self) -> list[str]:
        """
        list of available models for the provider
        """
        if not self._available_models:
            self._available_models = self.GetAvailableModels()

        return self._available_models

    @property
    def selected_model(self) -> str|None:
        """
        The currently selected model for the provider
        """
        name : str|None = self.settings.get_str('model')
        return name.strip() if name else None

    @property
    def recommended_min_chunk_seconds(self) -> float:
        """
        Recommended minimum audio chunk length: providers with per-request
        overhead or speaker tracking prefer longer chunks, constrained
        engines prefer shorter ones. Explicit user settings always win.
        """
        return 8.0

    @property
    def recommended_max_chunk_seconds(self) -> float:
        """
        Recommended maximum audio chunk length (see recommended_min_chunk_seconds).
        """
        return 60.0

    def GetAvailableModels(self) -> list[str]:
        """
        Returns a list of possible models for the provider
        """
        raise NotImplementedError

    def ResetAvailableModels(self) -> None:
        """
        Reset the available models for the provider
        """
        self._available_models = []

    def GetInformation(self, ffmpeg_available : bool|None = True, torch_device : str = "Unknown",
                       display_language : str|None = None) -> str|None:
        """
        Returns information about the provider settings.

        ffmpeg_available None means the check has not run yet; the guidance
        paragraph shows until a successful run proves ffmpeg valid. torch_device
        "Unknown" means no Qwen transcription has completed yet. A language
        hint the provider cannot use adds a warning paragraph.
        """
        parts : list[str] = []
        if ffmpeg_available is not True:
            parts.append(_(
                "<p>Audio extraction needs <a href=\"https://ffmpeg.org/download.html\">ffmpeg</a> installed."
            ))
        info = self._get_provider_information(torch_device)
        if info:
            parts.append(info)
        warning = self.LanguageWarning(display_language)
        if warning:
            parts.append(f"<p><b>{_('Warning')}:</b> {html.escape(warning)}</p>")
        return "\n".join(parts) if parts else None

    def LanguageWarning(self, display_language : str|None = None) -> str|None:
        """
        Why the configured language hint cannot be used, or None when it
        resolves (or is empty, meaning auto-detect).
        """
        try:
            self.ResolveLanguageCode(self.settings.get_str('language'), display_language)
        except SubtitleError as e:
            return str(e)
        return None

    def _get_provider_information(self, torch_device : str = "Unknown") -> str|None:
        """
        Provider-specific text, with the no-key walkthrough when defined and
        no effective key is configured. Qwen defines no walkthrough: it is
        keyless, so there is nothing to walk through.
        """
        # Only Qwen Local cares about torch state.
        if not self.settings.get_str('api_key') and self.information_noapikey:
            return self.information_noapikey
        return getattr(self, 'information', None)

    @staticmethod
    def ResolveTorchDevice(torch_module : object|None) -> str:
        """
        Record the resolved torch device without importing torch: None (not
        imported, e.g. non-local providers) stays "Unknown", otherwise the
        capability probe result. Never call with a fresh import; the caller
        is a Qwen run that already paid for it.
        """
        if torch_module is None:
            return "Unknown"
        try:
            cuda = torch_module.cuda  # type: ignore[union-attr]
            return "cuda:0" if cuda.is_available() else "cpu"
        except Exception:
            return "Unknown"

    def GetTranscriptionClient(self, settings : SettingsType) -> TranscriptionClient:
        """
        Returns a new instance of the transcription client for this provider
        """
        raise NotImplementedError

    def GetOptions(self, settings : SettingsType) -> GuiSettingsType:
        """
        Returns the configurable options for the provider
        """
        raise NotImplementedError

    def ValidateSettings(self) -> bool:
        """
        Validate the settings for the provider
        """
        return True

    def ResolveLanguageCode(self, language : str|None, display_language : str|None = None) -> str|None:
        """
        Turn a user's language hint into whatever the backend expects, or
        None for auto-detection. Called by the UI/CLI before a run starts
        so clients only ever receive a valid value. Raises SubtitleError
        for hints the backend cannot use.
        """
        return language.strip() if language and language.strip() else None

    def ResolveLanguageLocale(self, language : str|None, display_language : str|None = None) -> Locale|None:
        """
        Shared first step for providers that need a specific format:
        a Babel locale for the hint, None for an empty hint, or a
        SubtitleError when the hint is not a recognisable language.
        """
        if not language or not language.strip():
            return None

        locale = ResolveLanguage(language, display_language)
        if locale is None:
            raise SubtitleError(_("Unrecognised language '{}': use a language name or code, or leave empty to auto-detect").format(language.strip()))

        return locale

    def UpdateSettings(self, settings : SettingsType) -> None:
        """
        Update the settings for the provider
        """
        if isinstance(settings, Options):
            options = cast(Options, settings)
            options.InitialiseProviderSettings(self.name, self.settings)
            settings = options.provider_settings[self.name]

        for k, v in settings.items():
            if k in self.settings:
                self.settings[k] = v

    @classmethod
    def get_providers(cls) -> dict:
        """
        Return a dictionary of all available transcription providers
        """
        if not cls.__subclasses__():
            logging.info(_("Loading transcription providers"))
            from . import Providers  # type: ignore[ignore-unused]

        providers = {cast(TranscriptionProvider, provider).name: provider for provider in cls.__subclasses__()}

        return providers

    @classmethod
    def create_provider(cls, name : str, provider_settings : SettingsType) -> TranscriptionProvider:
        """
        Create a new instance of the provider with the given name
        """
        providers = cls.get_providers().items()
        name_cf = name.casefold()
        for provider_name, provider in providers:
            if provider_name.casefold() == name_cf:
                return provider(provider_settings)

        raise ValueError(f"Unknown transcription provider: {name}")
