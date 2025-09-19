"""
PySubtrans - Subtitle Translation Library

A Python library for translating subtitle files using various LLMs as translators.

Basic Usage
-----------
    >>> from PySubtrans import init_options, init_subtitles, init_translator
    >>>
    >>> # Load subtitles from file
    >>> subs = init_subtitles(filepath="movie.srt")
    >>>
    >>> # Configure translation options
    >>> opts = init_options(provider="openai", model="gpt-4o-mini", api_key="sk-...", prompt="Translate these subtitles into Spanish")
    >>>
    >>> # Create translator and translate
    >>> translator = init_translator(opts)
    >>> translator.Translate(subs)
    >>>
    >>> # Save translated subtitles
    >>> subs.SaveSubtitles("movie_translated.srt")
"""
from __future__ import annotations

from collections.abc import Mapping

from PySubtrans.Helpers import GetInputPath
from PySubtrans.Options import Options
from PySubtrans.SettingsType import SettingType, SettingsType
from PySubtrans.SubtitleBuilder import SubtitleBuilder
from PySubtrans.SubtitleFormatRegistry import SubtitleFormatRegistry
from PySubtrans.Subtitles import Subtitles
from PySubtrans.SubtitleProject import SubtitleProject
from PySubtrans.SubtitleTranslator import SubtitleTranslator
from PySubtrans.TranslationProvider import TranslationProvider
from PySubtrans.version import __version__


def init_options(
    provider: str|None = None,
    model: str|None = None,
    api_key: str|None = None,
    prompt: str|None = None,
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
    prompt : str or None, optional
        High level prompt for the translator, e.g. "Translate these subtitles for Alien (1979) into French".
    **settings : SettingType
        Additional keyword settings to configure the translation provider. See :class:`Options` for available settings.

    Returns
    -------
    Options
        An Options instance with the specified configuration.

    Examples
    --------
    >>> from PySubtrans import init_options
    >>> opts = init_options(provider="openai", model="gpt-5-mini", api_key="sk-...", prompt="Translate these subtitles into Spanish")
    """
    combined_settings = SettingsType(settings)

    explicit_settings = {
        'provider': provider,
        'model': model,
        'api_key': api_key,
        'prompt': prompt,
    }
    combined_settings.update({k: v for k, v in explicit_settings.items() if v is not None})

    return Options(combined_settings)

def init_subtitles(filepath: str|None, content: str|None) -> Subtitles:
    """
    Initialise a :class:`Subtitles` instance and optionally load content from a file or string.

    Parameters
    ----------
    filepath : str|None
        Path to the subtitle file to load.

    content : str|None
        Subtitle content as a string. Attempts to auto-detect the format by contents.

    Returns
    -------
    Subtitles : An initialised subtitles instance.

    Examples
    --------
    Load subtitles from a file:

    >>> from PySubtrans import init_subtitles
    >>> subs = init_subtitles(filepath="movie.srt")
    >>> print(len(subs))

    Load subtitles from a string:

    >>> srt_content = "1\\n00:00:01,000 --> 00:00:03,000\\nHello world"
    >>> subs = init_subtitles(content=srt_content)
    >>> print(subs[0].text)
    """
    if filepath and content:
        raise ValueError("Only one of 'filepath' or 'content' should be provided, not both.")

    if filepath:
        normalised_path = GetInputPath(filepath)
        subtitles = Subtitles(normalised_path)
        subtitles.LoadSubtitles(normalised_path)
        return subtitles

    if content:
        format = SubtitleFormatRegistry.detect_format_from_content(content)
        file_handler = SubtitleFormatRegistry.create_handler(format)
        subtitles = Subtitles()
        subtitles.LoadSubtitlesFromString(content, file_handler=file_handler)
        return subtitles

    return Subtitles()


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

    Examples
    --------
    Create a basic project:

    >>> from PySubtrans import init_project
    >>> project = init_project("movie.srt")
    >>> print(len(project.subtitles))
    150

    Create a persistent project:

    >>> project = init_project("movie.srt", persistent=True)
    >>> # Project state will be saved to .subtrans file
    >>> project.Save()
    """
    project = SubtitleProject(persistent=persistent)
    normalised_path = GetInputPath(filepath)

    if normalised_path:
        project.InitialiseProject(normalised_path)

    return project


def init_translator(settings: Options|Mapping[str, SettingType]) -> SubtitleTranslator:
    """
    Return a ready-to-use :class:`SubtitleTranslator` using the specified settings.

    Parameters
    ----------
    settings : Options or Mapping[str, SettingType]
        The translator settings. This should specify the provider and model to use, along with extra configuration options as needed.

    Validation
    ----------
    - Checks that `settings` is either an :class:`Options` instance or a mapping; if a mapping, it is converted to :class:`Options`.
    - Validates the settings for the translation provider.

    Exceptions
    ----------
    ValueError
        If the settings are invalid for the selected translation provider.

    Returns
    -------
    SubtitleTranslator
        A ready-to-use subtitle translator configured with the given settings.

    Examples
    --------
    Create translator from Options:

    >>> from PySubtrans import init_options, init_translator
    >>> opts = init_options(provider="openai", model="gpt-4o-mini", api_key="sk-...")
    >>> translator = init_translator(opts)

    Create translator from dictionary:

    >>> settings = {"provider": "google", "api_key": "your-key"}
    >>> translator = init_translator(settings)
    """
    if not isinstance(settings, Options):
        if isinstance(settings, Mapping):
            settings = Options(SettingsType(settings))
        else:
            raise TypeError("settings must be an Options instance or a mapping of option values")

    translation_provider = TranslationProvider.get_provider(settings)
    if not translation_provider.ValidateSettings():
        message = translation_provider.validation_message or f"Invalid settings for provider {settings.provider}"
        raise ValueError(message)

    settings.InitialiseInstructions()

    return SubtitleTranslator(settings, translation_provider)

def preprocess_subtitles(subtitles: Subtitles, options: Options) -> None:
    """
    Preprocess subtitles to fix common issues before translation.

    This function modifies the subtitles in place.

    Parameters
    ----------
    subtitles : Subtitles
        The subtitles to preprocess.
    options : Options
        Configuration options for preprocessing.

    Returns
    -------
    None

    Examples
    --------
    >>> from PySubtrans import init_subtitles, init_options, preprocess_subtitles
    >>> subs = init_subtitles(filepath="movie.srt")
    >>> opts = PySubtrans.Options(max_line_duration=5.0, whitespaces_to_newline=True)
    >>> preprocess_subtitles(subs, opts)
    """
    from PySubtrans.SubtitleProcessor import SubtitleProcessor

    if not subtitles or not subtitles.originals:
        raise ValueError("No subtitles to preprocess")

    preprocessor = SubtitleProcessor(options)
    subtitles.PreProcess(preprocessor)

__all__ = [
    '__version__',
    'Options',
    'Subtitles',
    'SubtitleBuilder',
    'SubtitleProject',
    'SubtitleTranslator',
    'TranslationProvider',
    'init_options',
    'init_project',
    'init_subtitles',
    'init_translator',
]
