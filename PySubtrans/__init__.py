from __future__ import annotations

from collections.abc import Mapping

from PySubtrans.Helpers import GetInputPath
from PySubtrans.Options import Options
from PySubtrans.SettingsType import SettingType, SettingsType
from PySubtrans.SubtitleProject import SubtitleProject
from PySubtrans.SubtitleTranslator import SubtitleTranslator
from PySubtrans.TranslationProvider import TranslationProvider
from PySubtrans.version import __version__


def init_options(
    provider: str|None = None,
    model: str|None = None,
    api_key: str|None = None,
    instruction_file: str|None = None,
    **settings: SettingType,
) -> Options:
    """Return an :class:`Options` instance configured for a translation provider."""
    combined_settings = SettingsType(settings)

    if provider is not None:
        combined_settings['provider'] = provider
    if model is not None:
        combined_settings['model'] = model
    if api_key is not None:
        combined_settings['api_key'] = api_key
    if instruction_file is not None:
        combined_settings['instruction_file'] = instruction_file

    return Options(combined_settings)


def init_project(filepath: str|None, persistent: bool = False) -> SubtitleProject:
    """Create a :class:`SubtitleProject` and optionally load subtitles from *filepath*."""
    project = SubtitleProject(persistent=persistent)
    normalised_path = GetInputPath(filepath)

    if normalised_path:
        project.InitialiseProject(normalised_path)

    return project


def init_translator(project: SubtitleProject, settings: Options|Mapping[str, SettingType]) -> SubtitleTranslator:
    """Return a ready-to-use :class:`SubtitleTranslator` for *project* using *settings*."""
    if not isinstance(project, SubtitleProject):
        raise TypeError("project must be a SubtitleProject instance")

    if not isinstance(settings, Options):
        if isinstance(settings, Mapping):
            settings = Options(SettingsType(settings))
        else:
            raise TypeError("settings must be an Options instance or a mapping of option values")

    project.UpdateProjectSettings(settings)

    translation_provider = TranslationProvider.get_provider(settings)
    if not translation_provider.ValidateSettings():
        message = translation_provider.validation_message or f"Invalid settings for provider {settings.provider}"
        raise ValueError(message)

    settings.InitialiseInstructions()

    return SubtitleTranslator(settings, translation_provider)


__all__ = [
    '__version__',
    'Options',
    'SubtitleProject',
    'SubtitleTranslator',
    'TranslationProvider',
    'init_options',
    'init_project',
    'init_translator',
]
