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
    """
    Create and return an :class:`Options` instance configured for a translation provider.

    Parameters
    ----------
    provider : str or None, optional
        The name of the translation provider to use (e.g., "openai", "google").
    model : str or None, optional
        The model identifier to use for translation (e.g., "gpt-3.5-turbo").
    api_key : str or None, optional
        API key for authenticating with the translation provider.
    instruction_file : str or None, optional
        Path to a file containing custom translation instructions.
    **settings : SettingType
        Additional keyword settings to configure the translation provider.

    Returns
    -------
    Options
        An Options instance with the specified configuration.

    Examples
    --------
    >>> from PySubtrans import init_options
    >>> opts = init_options(provider="openai", model="gpt-3.5-turbo", api_key="sk-...", custom_setting="value")
    >>> print(opts.provider)
    openai
    """
    combined_settings = SettingsType(settings)

    explicit_settings = {
        'provider': provider,
        'model': model,
        'api_key': api_key,
        'instruction_file': instruction_file,
    }
    combined_settings.update({k: v for k, v in explicit_settings.items() if v is not None})

    return Options(combined_settings)


def init_project(filepath: str|None, persistent: bool = False) -> SubtitleProject:
    """
    Create a :class:`SubtitleProject` and optionally load subtitles from *filepath*.

    Parameters
    ----------
    filepath : str or None
        Path to the subtitle file to load into the project.
    persistent : bool, optional
        If True, enables persistent project state by creating and managing a
        `.subtrans` project file in the working directory. This allows the project
        to be saved and restored across sessions. If False (default), the project
        is not persisted to disk.

    Returns
    -------
    SubtitleProject
        The initialized subtitle project.
    """
    project = SubtitleProject(persistent=persistent)
    normalised_path = GetInputPath(filepath)

    if normalised_path:
        project.InitialiseProject(normalised_path)

    return project


def init_translator(project: SubtitleProject, settings: Options|Mapping[str, SettingType]) -> SubtitleTranslator:
    """
    Return a ready-to-use :class:`SubtitleTranslator` for the given subtitle project using the specified settings.

    Parameters
    ----------
    project : SubtitleProject
        The subtitle project to be translated. Must be an instance of :class:`SubtitleProject`.
    settings : Options or Mapping[str, SettingType]
        The translation settings. Can be an :class:`Options` instance or a mapping of option values.

    Validation
    ----------
    - Checks that `project` is a :class:`SubtitleProject` instance.
    - Checks that `settings` is either an :class:`Options` instance or a mapping; if a mapping, it is converted to :class:`Options`.
    - Validates the settings for the translation provider.

    Exceptions
    ----------
    TypeError
        If `project` is not a :class:`SubtitleProject` instance, or if `settings` is not an :class:`Options` instance or a mapping.
    ValueError
        If the settings are invalid for the selected translation provider.

    Returns
    -------
    SubtitleTranslator
        A ready-to-use subtitle translator configured with the given settings.
    """
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
