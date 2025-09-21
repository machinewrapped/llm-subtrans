"""
PySubtrans - Subtitle Translation Library

A Python library for translating subtitle files using various LLMs as translators.

Basic Usage
-----------
    >>> from PySubtrans import init_options, init_subtitles, init_translator
    >>>
    >>> # Configure translation options
    >>> opts = init_options(
    ...     provider="openai",
    ...     model="gpt-4o-mini",
    ...     api_key="sk-...",
    ...     prompt="Translate these subtitles into Spanish",
    ...     preprocess_subtitles=True,
    ...     scene_threshold=90.0,
    ...     min_batch_size=2,
    ...     max_batch_size=60,
    ... )
    >>>
    >>> # Load subtitles from file with automatic preprocessing and batching
    >>> subs = init_subtitles(filepath="movie.srt", options=opts)
    >>>
    >>> # Create translator and translate the prepared subtitles
    >>> translator = init_translator(opts)
    >>> translator.TranslateSubtitles(subs)
    >>>
    >>> # Save translated subtitles
    >>> subs.SaveSubtitles("movie_translated.srt")
"""
from __future__ import annotations

from collections.abc import Mapping

from PySubtrans.Helpers import GetInputPath
from PySubtrans.Options import Options
from PySubtrans.SettingsType import SettingType, SettingsType
from PySubtrans.SubtitleBatcher import SubtitleBatcher
from PySubtrans.SubtitleBuilder import SubtitleBuilder
from PySubtrans.SubtitleEditor import SubtitleEditor
from PySubtrans.SubtitleFormatRegistry import SubtitleFormatRegistry
from PySubtrans.SubtitleLine import SubtitleLine
from PySubtrans.Subtitles import Subtitles
from PySubtrans.SubtitleScene import SubtitleScene
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
        The name of the translation provider to use (e.g., "openai", "gemini").
    model : str or None, optional
        The model identifier to use for translation (e.g., "gpt-5-mini").
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

    options = Options(combined_settings)

    options.InitialiseInstructions()

    return options


def init_subtitles(
    filepath: str|None = None,
    content: str|None = None,
    *,
    options: Options|Mapping[str, SettingType]|None = None,
    auto_batch: bool = True,
) -> Subtitles:
    """
    Initialise a :class:`Subtitles` instance and optionally load content from a file or string.

    Parameters
    ----------
    filepath : str|None
        Path to the subtitle file to load.

    content : str|None
        Subtitle content as a string. Attempts to auto-detect the format by contents.

    options : Options or mapping, optional
        Settings applied to the subtitles before preprocessing or batching. When omitted a default
        :class:`Options` instance is created. Provide batching values such as ``scene_threshold``,
        ``min_batch_size`` and ``max_batch_size`` via this mapping.

    auto_batch : bool, optional
        If True (default), automatically divide the subtitles into scenes and batches using
        :func:`batch_subtitles` and the values supplied in ``options``.

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
    elif content:
        format = SubtitleFormatRegistry.detect_format_from_content(content)
        file_handler = SubtitleFormatRegistry.create_handler(format)
        subtitles = Subtitles()
        subtitles.LoadSubtitlesFromString(content, file_handler=file_handler)
    else:
        return Subtitles()

    if not subtitles.originals:
        raise ValueError("No subtitle lines were loaded from the supplied input")

    options_supplied = options is not None
    if options is not None and not isinstance(options, (Options, Mapping)):
        raise TypeError("options must be an Options instance, mapping, or None")
    options = Options(options)

    should_preprocess = options.get_bool('preprocess_subtitles') if options_supplied else True
    if should_preprocess:
        preprocess_subtitles(subtitles, options)

    if auto_batch:
        batch_subtitles(
            subtitles,
            scene_threshold=options.get_float('scene_threshold'),
            min_batch_size=options.get_int('min_batch_size'),
            max_batch_size=options.get_int('max_batch_size'),
            fix_overlaps=options.get_bool('prevent_overlapping_times'),
        )

    return subtitles


def batch_subtitles(
    subtitles: Subtitles,
    scene_threshold: float,
    min_batch_size: int,
    max_batch_size: int,
    *,
    fix_overlaps: bool = False,
) -> list[SubtitleScene]:
    """
    Divide subtitles into scenes and batches using :class:`SubtitleBatcher`.

    Parameters
    ----------
    subtitles : Subtitles
        The subtitle collection to batch.
    scene_threshold : float
        Minimum gap between lines (in seconds) to consider a new scene.
    min_batch_size : int
        Minimum number of lines per batch.
    max_batch_size : int
        Maximum number of lines per batch.
    fix_overlaps : bool, optional
        If True, adjust overlapping subtitle times while batching.

    Returns
    -------
    list[SubtitleScene]
        The generated scenes containing batches of subtitle lines.
    """
    if not subtitles:
        raise ValueError("No subtitles supplied for batching")

    if not subtitles.originals:
        raise ValueError("No subtitle lines available to batch")

    batcher = SubtitleBatcher(SettingsType({
        'scene_threshold': scene_threshold,
        'min_batch_size': min_batch_size,
        'max_batch_size': max_batch_size,
        'prevent_overlapping_times': fix_overlaps,
    }))

    with SubtitleEditor(subtitles) as editor:
        editor.AutoBatch(batcher)

    return subtitles.scenes


def init_translator(settings: Options|Mapping[str, SettingType]) -> SubtitleTranslator:
    """
    Return a ready-to-use :class:`SubtitleTranslator` using the specified settings.

    Parameters
    ----------
    settings : Options or Mapping[str, SettingType]
        The translator settings. This should specify the provider and model to use, along with extra configuration options as needed.

    Validation
    ----------
    - Validates the settings for the translation provider.

    Exceptions
    ----------
    ValueError
        If the settings are invalid.

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

    >>> settings = {"provider": "gemini", "api_key": "your-key", "model": "gemini-2.5-flash"}
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

    return SubtitleTranslator(settings, translation_provider)


def init_project(
    settings: Options|Mapping[str, SettingType]|None = None,
    filepath: str|None = None,
    persistent: bool = False,
    *,
    auto_batch: bool = True,
) -> SubtitleProject:
    """
    Create a :class:`SubtitleProject` and optionally load subtitles from *filepath*.

    Parameters
    ----------
    settings : Options, Mapping[str, SettingType], or None, optional
        Settings to configure the translation workflow. When provided, the translator will be automatically initialised and
        the same settings will be used to preprocess and batch the subtitles.
    filepath : str or None, optional
        Path to the subtitle file to load into the project.
    persistent : bool, optional
        If True, enables persistent project state by creating a `.subtrans` project file for the job.
    auto_batch : bool, optional
        If True (default), automatically divide the subtitles into scenes and batches using
        :class:`SubtitleBatcher`.

    Returns
    -------
    SubtitleProject
        The initialized subtitle project.

    Notes
    -----
    Subtitles are preprocessed and automatically divided into scenes and batches using :class:`SubtitleBatcher` with the supplied
    settings (or default values when settings are omitted).

    Examples
    --------
    Create a basic project:

    >>> from PySubtrans import init_project
    >>> project = init_project(filepath="movie.srt")

    Create a project with translator ready for translation:

    >>> settings = {"provider": "OpenAI", "model": "gpt-4o", "target_language": "Spanish", "api_key": "your-key"}
    >>> project = init_project(settings, filepath="movie.srt")
    >>> project.TranslateSubtitles()

    Create a persistent project:

    >>> project = init_project(filepath="movie.srt", persistent=True)
    >>> project.SaveProject()
    """
    project = SubtitleProject(persistent=persistent)
    normalised_path = GetInputPath(filepath)

    if normalised_path:
        project.InitialiseProject(normalised_path)

    options_supplied = settings is not None
    if settings is not None and not isinstance(settings, (Options, Mapping)):
        raise TypeError("settings must be an Options instance, mapping, or None")
    options = Options(settings)

    project.UpdateProjectSettings(options)

    subtitles = project.subtitles
    if subtitles and subtitles.originals:
        should_preprocess = options.get_bool('preprocess_subtitles') if options_supplied else True

        if should_preprocess:
            preprocess_subtitles(subtitles, options)

        if auto_batch:
            batch_subtitles(
                subtitles,
                scene_threshold=options.get_float('scene_threshold'),
                min_batch_size=options.get_int('min_batch_size'),
                max_batch_size=options.get_int('max_batch_size'),
                fix_overlaps=options.get_bool('prevent_overlapping_times'),
            )

    if options.provider:
        project.InitialiseTranslator(options)

    return project


def preprocess_subtitles(
    subtitles: Subtitles,
    options: Options|Mapping[str, SettingType]|None = None,
) -> None:
    """
    Preprocess subtitles to fix common issues before translation.

    This function modifies the subtitles in place.

    Parameters
    ----------
    subtitles : Subtitles
        The subtitles to preprocess.
    options : Options or mapping, optional
        Configuration options for preprocessing. When omitted, default options are used.

    Returns
    -------
    None
    """
    from PySubtrans.SubtitleProcessor import SubtitleProcessor

    if not subtitles or not subtitles.originals:
        raise ValueError("No subtitles to preprocess")

    if isinstance(options, Options):
        preprocess_options = options
    elif isinstance(options, Mapping):
        preprocess_options = Options(SettingsType(options))
    elif options is None:
        preprocess_options = Options()
    else:
        raise TypeError("options must be an Options instance, mapping, or None")

    preprocessor = SubtitleProcessor(preprocess_options)
    with SubtitleEditor(subtitles) as editor:
        editor.PreProcess(preprocessor)

__all__ = [
    '__version__',
    'Options',
    'Subtitles',
    'SubtitleScene',
    'SubtitleLine',
    'SubtitleBatcher',
    'SubtitleBuilder',
    'SubtitleEditor',
    'SubtitleProject',
    'SubtitleTranslator',
    'TranslationProvider',
    'init_options',
    'batch_subtitles',
    'init_project',
    'init_subtitles',
    'init_translator',
    'preprocess_subtitles',
]
