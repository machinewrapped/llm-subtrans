"""
PySubtrans - Subtitle Translation Library

A Python library for translating subtitle files using various LLMs as translators.

Basic Usage
-----------
    from PySubtrans import init_options, init_subtitles, init_translator

    # Configure options
    opts = init_options(
            provider="openai",
            model="gpt-5-mini",
            api_key="sk-...",
            prompt="Translate these subtitles into Spanish",
        )

    # Load subtitles from file and prepare them for translation
    subs = init_subtitles(filepath="movie.srt", options=opts)

    # Create translator and translate the prepared subtitles
    translator = init_translator(opts)
    translator.TranslateSubtitles(subs)

    # Save translated subtitles
    subs.SaveSubtitles("movie_translated.srt")
"""
from __future__ import annotations

from collections.abc import Mapping

from PySubtrans.Helpers import GetInputPath
from PySubtrans.Options import Options
from PySubtrans.SettingsType import SettingType, SettingsType
from PySubtrans.SubtitleBatcher import SubtitleBatcher
from PySubtrans.SubtitleBuilder import SubtitleBuilder
from PySubtrans.SubtitleEditor import SubtitleEditor
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.SubtitleFormatRegistry import SubtitleFormatRegistry
from PySubtrans.SubtitleLine import SubtitleLine
from PySubtrans.Subtitles import Subtitles
from PySubtrans.SubtitleProcessor import SubtitleProcessor
from PySubtrans.SubtitleProject import SubtitleProject
from PySubtrans.SubtitleScene import SubtitleScene
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
        High level prompt for the translator, e.g. "Translate these subtitles for Alien (1979) into French and make them scary".
    **settings : SettingType
        Additional keyword settings to configure the translation process. See :class:`Options` for available settings. If not specified, default values are assigned.

    Returns
    -------
    Options
        An Options instance with the specified configuration.

    Examples
    --------
    from PySubtrans import init_options
    opts = init_options(provider="openai", model="gpt-5-mini", api_key="sk-   ", prompt="Translate these subtitles into Spanish")
    """
    settings = SettingsType(settings)

    explicit_settings = {
        'provider': provider,
        'model': model,
        'api_key': api_key,
        'prompt': prompt,
    }
    settings.update({k: v for k, v in explicit_settings.items() if v is not None})

    options = Options(settings)

    options.InitialiseInstructions()

    return options

def init_subtitles(
    filepath: str|None = None,
    content: str|None = None,
    *,
    options: Options|SettingsType|None = None,
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

    options : Options or SettingsType, optional
        Settings for pre-processing and batching subtitles, e.g. `scene_threshold`, `min_batch_size`, `max_batch_size`.

    auto_batch : bool, optional
        If True (default), automatically divide the subtitles into scenes and batches ready for translation.

    Returns
    -------
    Subtitles : An initialised subtitles instance.

    Examples
    --------
    from PySubtrans import init_subtitles

    # Load subtitles from a file:
    subs = init_subtitles(filepath="movie.srt")

    # Load subtitles from a string:
    srt_content = "1\\n00:00:01,000 --> 00:00:03,000\\nHello world"
    subs = init_subtitles(content=srt_content)
    """
    if filepath and content:
        raise SubtitleError("Only one of 'filepath' or 'content' should be provided, not both.")

    if filepath:
        subtitles = Subtitles(filepath)
        subtitles.LoadSubtitles()
    elif content:
        format = SubtitleFormatRegistry.detect_format_from_content(content)
        file_handler = SubtitleFormatRegistry.create_handler(format)
        subtitles = Subtitles()
        subtitles.LoadSubtitlesFromString(content, file_handler=file_handler)
    else:
        return Subtitles()

    if not subtitles.originals:
        raise SubtitleError("No subtitle lines were loaded from the supplied input")

    options = Options(options)

    if options.get_bool('preprocess_subtitles'):
        preprocess_subtitles(subtitles, options)

    if auto_batch:
        batch_subtitles(
            subtitles,
            scene_threshold=options.get_float('scene_threshold') or 60.0,
            min_batch_size=options.get_int('min_batch_size') or 1,
            max_batch_size=options.get_int('max_batch_size') or 100,
            prevent_overlap=options.get_bool('prevent_overlapping_times'),
        )

    return subtitles

def init_translation_provider(
    provider : str,
    options : Options|SettingsType|Mapping[str, SettingType],
) -> TranslationProvider:
    """
    Initialise and validate a :class:`TranslationProvider` instance.

    Parameters
    ----------
    provider : str
        The provider name registered with :class:`TranslationProvider`.
    options : Options or mapping
        Translator options containing the provider configuration (vary depending on the provider).

    Returns
    -------
    TranslationProvider
        A provider instance with validated credentials and settings.

    Examples
    --------
    from PySubtrans import init_options, init_translation_provider, init_translator

    options = init_options(
        model="gpt-5-mini",
        api_key="sk-...",
        prompt="Translate these subtitles into {target_language}",
        target_language="French",
    )
    provider = init_translation_provider("openai", options)
    translator = init_translator(options, translation_provider=provider)
    """

    if not provider:
        raise SubtitleError("Translation provider name is required")

    if options is None:
        raise SubtitleError("Translation options are required to initialise a provider")

    if not isinstance(options, Options):
        options = Options(options)

    options.provider = provider

    try:
        translation_provider = TranslationProvider.get_provider(options)
    except ValueError as exc:
        raise SubtitleError(str(exc)) from exc

    if not translation_provider.ValidateSettings():
        message = translation_provider.validation_message or f"Invalid settings for provider {provider}"
        raise SubtitleError(message)

    return translation_provider


def init_translator(
    settings : Options|SettingsType,
    translation_provider : TranslationProvider|None = None,
) -> SubtitleTranslator:
    """
    Return a ready-to-use :class:`SubtitleTranslator` using the specified settings.

    Parameters
    ----------
    settings : Options or SettingsType
        The translator settings. This should specify the provider and model to use, along with extra configuration options as needed.
    translation_provider : TranslationProvider or None, optional
        An pre-configured :class:`TranslationProvider` instance (if not specified a provider is created automatically based on the settings).

    Exceptions
    ----------
    SubtitleError
        If the settings are invalid.

    Returns
    -------
    SubtitleTranslator
        A ready-to-use subtitle translator configured with the given settings.

    Examples
    --------
    from PySubtrans import init_options, init_translator

    # Create translator from Options
    opts = init_options(provider="openai", model="gpt-5-mini", api_key="sk-   ", prompt="Translate these subtitles into Spanish")
    translator = init_translator(opts)

    # Create translator from dictionary
    settings = {"provider": "gemini", "api_key": "your-key", "model": "gemini-2.5-flash"}
    translator = init_translator(settings)

    # Create translator with a pre-initialised TranslationProvider
    provider_options = init_options(model="gpt-5-mini", api_key="sk-...")
    provider = init_translation_provider("openai", provider_options)
    options = init_options(prompt="Translate these subtitles into Spanish")
    translator = init_translator(options, translation_provider=provider)
    """
    options = Options(settings)

    options.InitialiseInstructions()

    if translation_provider is None:
        translation_provider = TranslationProvider.get_provider(options)
    else:
        provider_name = translation_provider.name
        if options.provider and options.provider.lower() != provider_name.lower():
            raise SubtitleError(
                f"Translation provider mismatch: expected {options.provider}, got {provider_name}"
            )

        if not options.provider:
            options.provider = provider_name

        translation_provider.UpdateSettings(options)

    if not translation_provider.ValidateSettings():
        message = translation_provider.validation_message or f"Invalid settings for provider {options.provider}"
        raise SubtitleError(message)

    return SubtitleTranslator(options, translation_provider)


def init_project(
    settings: Options|SettingsType|None = None,
    *,
    filepath: str|None = None,
    persistent: bool = False,
    auto_batch: bool = True,
) -> SubtitleProject:
    """
    Create a :class:`SubtitleProject`, optionally load subtitles from *filepath* and prepare it for translation.

    Parameters
    ----------
    settings : Options, SettingsType, or None, optional
        Settings to configure the translation workflow.
    filepath : str or None, optional
        Path to the subtitle file to load.
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
    Subtitles are preprocessed and batched using the supplied settings or default values.

    Examples
    --------
    from PySubtrans import init_project, init_translator

    # Create a minimal project
    project = init_project(filepath="movie.srt")

    # Create a project and translate it with a translator
    settings = {"provider": "OpenAI", "model": "gpt-4o", "target_language": "Spanish", "api_key": "your-key"}
    project = init_project(settings, filepath="movie.srt")
    translator = init_translator(settings)
    project.TranslateSubtitles(translator)

    # Create a persistent project
    project = init_project(settings, filepath="movie.srt", persistent=True)
    project.SaveProject()
    """
    project = SubtitleProject(persistent=persistent)

    options = Options(settings)

    normalised_path = GetInputPath(filepath)

    if normalised_path:
        project.InitialiseProject(normalised_path)

        if project.existing_project:
            project_settings = project.GetProjectSettings()
            options.update(project_settings)

        if settings:
            project.UpdateProjectSettings(settings)

        subtitles = project.subtitles

        if not subtitles or not subtitles.originals:
            raise SubtitleError(f"No subtitles were loaded from '{normalised_path}'")

        if options.get_bool('preprocess_subtitles'):
            preprocess_subtitles(subtitles, options)

        if auto_batch:
            batch_subtitles(
                subtitles,
                scene_threshold=options.get_float('scene_threshold') or 60.0,
                min_batch_size=options.get_int('min_batch_size') or 1,
                max_batch_size=options.get_int('max_batch_size') or 100,
                prevent_overlap=options.get_bool('prevent_overlapping_times'),
            )

    return project


def preprocess_subtitles(
    subtitles: Subtitles,
    settings: Options|SettingsType|None = None,
) -> None:
    """
    Preprocess subtitles to fix common issues before translation.

    Parameters
    ----------
    subtitles : Subtitles
        The subtitles to preprocess.
    options : Options or SettingsType, optional
        Configuration options for preprocessing. When omitted, default options are used.

    Returns
    -------
    None
    """
    if not subtitles or not subtitles.originals:
        raise SubtitleError("No subtitles to preprocess")

    preprocessor = SubtitleProcessor(settings or Options())
    with SubtitleEditor(subtitles) as editor:
        editor.PreProcess(preprocessor)

def batch_subtitles(
    subtitles: Subtitles,
    scene_threshold: float,
    min_batch_size: int,
    max_batch_size: int,
    *,
    prevent_overlap: bool = False,
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
    prevent_overlap : bool, optional
        If True, adjust overlapping subtitle times while batching.

    Returns
    -------
    list[SubtitleScene]
        The generated scenes containing batches of subtitle lines.
    """
    if not subtitles:
        raise SubtitleError("No subtitles supplied for batching")

    if not subtitles.originals:
        raise SubtitleError("No subtitle lines available to batch")

    batcher = SubtitleBatcher(SettingsType({
        'scene_threshold': scene_threshold,
        'min_batch_size': min_batch_size,
        'max_batch_size': max_batch_size,
        'prevent_overlapping_times': prevent_overlap,
    }))

    with SubtitleEditor(subtitles) as editor:
        editor.AutoBatch(batcher)

    return subtitles.scenes


__all__ = [
    '__version__',
    'Options',
    'SettingsType',
    'Subtitles',
    'SubtitleScene',
    'SubtitleLine',
    'SubtitleBatcher',
    'SubtitleBuilder',
    'SubtitleEditor',
    'SubtitleFormatRegistry',
    'SubtitleProcessor',
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
