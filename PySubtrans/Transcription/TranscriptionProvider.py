from __future__ import annotations

from typing import cast

from PySubtrans.Options import Options
from PySubtrans.SettingsType import GuiSettingsType, SettingsType
from PySubtrans.Transcription.TranscriptionClient import TranscriptionClient


class TranscriptionProvider:
    """
    Base class for transcription service providers.

    Mirrors TranslationProvider but stays a separate hierarchy on purpose:
    transcription model catalogs, options and capability flags are disjoint
    from translation ones. API keys are shared at the Options level instead
    (see TranscriptionCoordinator.ResolveProviderSettings).
    """
    def __init__(self, name : str, settings : SettingsType):
        self.name : str = name
        self.settings : SettingsType = settings
        self._available_models : list[str] = []
        self.refresh_when_changed : list[str] = []
        self.validation_message : str|None = None

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

    def GetInformation(self) -> str|None:
        """
        Returns information about the provider settings
        """
        return None

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
