"""
PySubtrans - Subtitle Translation Library

A Python library for translating subtitle files using various LLMs as translators.

Basic Usage
-----------

# Configure options
opts = init_options(
        provider="OpenAI",
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
from enum import Enum

from PySubtrans.Helpers import GetInputPath
from PySubtrans.Helpers.InstructionsHelpers import LoadInstructions
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


class SettingsPrecedence(Enum):
    """Controls how :func:`init_project` merges project-file settings with caller-supplied settings."""
    User = 0        # caller's settings win; project-file values only fill missing keys
    Project = 1     # project-file settings override caller-supplied values (GUI-style)


def init_options(**settings: SettingType) -> Options:
    """
    Create and return an :class:`Options` instance containing settings for the translation workflow.

    Parameters
    ----------
    **settings : SettingType
        Keyword settings to configure the translation process.

        Valid settings depend on the chosen provider and likely include, e.g.

        provider = "OpenAI",
        model = "gpt-5-mini", 
        api_key = "sk-...", 

        Additional settings can be provided to customise the translation flow, e.g.

        prompt = "Translate these subtitles into [target_language]",
        target_language = "French",
        instruction_file = "instructions.txt",
        postprocess_translation = True,
        use_terminology_map = True,
        terminology_map = ["the Watch::la Garde", "Kingslayer::Régicide"]

        See :class:`Options` for available settings. 
        Options that are not specified will be assigned default values.

    Returns
    -------
    Options
        An Options instance with the specified configuration.

    Examples
    --------

    opts = init_options(provider="OpenAI", model="gpt-5-mini", api_key="sk-   ", prompt="Translate these subtitles into Spanish")
    """
    settings = SettingsType(settings)
    options = Options(settings)

    # Load and apply instructions if instruction file is specified
    instruction_file = options.get_str('instruction_file')
    if instruction_file:
        instructions = LoadInstructions(instruction_file)

        # Override prompt with explicit value if provided
        prompt = settings.get_str('prompt')
        if prompt:
            instructions.prompt = prompt

        options.InitialiseInstructions(instructions)

    return options

def init_subtitles(
    filepath: str|None = None,
    content: str|None = None,
    *,
    options: Options|SettingsType|None = None,
    auto_batch: bool = True,
    persistent_keys: list[str] | None = None,
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
        Also accepts settings such as `terminology_map`, `names`, and `substitutions` which are
        stored in the returned :class:`Subtitles` instance, so that they are available during translation.

    auto_batch : bool, optional
        If True (default), automatically divide the subtitles into scenes and batches ready for translation.

    persistent_keys : list of str, optional
        List of settings keys to store in the returned :class:`Subtitles` instance (by default all provided settings are stored). 

    Returns
    -------
    Subtitles : An initialised subtitles instance.

    Examples
    --------

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
    subtitles.UpdateSettings(options, keys=persistent_keys)

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

    options = init_options(
        model="gpt-5-mini",
        api_key="sk-...",
        prompt="Translate these subtitles into [target_language]",
        target_language="French",
    )
    provider = init_translation_provider("OpenAI", options)
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

    # Create translator from Options
    opts = init_options(provider="OpenAI", model="gpt-5-mini", api_key="sk-   ", prompt="Translate these subtitles into Spanish")
    translator = init_translator(opts)

    # Create translator from dictionary
    translator = init_translator({"provider": "gemini", "api_key": "your-key", "model": "gemini-2.5-flash"})

    # Create translator with a pre-initialised TranslationProvider
    provider = init_translation_provider("OpenAI", {"model": "gpt-5-mini", "api_key": "sk-..."})
    options = init_options(prompt="Translate these subtitles into Spanish")
    translator = init_translator(options, translation_provider=provider)

    # Subscribe to events (see TranslationEvents for full list):
    #   batch_translated, scene_translated, batch_updated, preprocessed
    #   terminology_updated  -- fired after each batch when use_terminology_map=True
    #   error, warning, info
    """
    options = Options(settings)

    translation_provider = translation_provider or TranslationProvider.get_provider(options)

    if not translation_provider.ValidateSettings():
        message = translation_provider.validation_message or f"Invalid settings for provider {options.provider}"
        raise SubtitleError(message)

    options.provider = translation_provider.name

    return SubtitleTranslator(options, translation_provider)


def init_project(
    settings: Options|SettingsType|None = None,
    *,
    filepath: str|None = None,
    persistent: bool = False,
    auto_batch: bool = True,
    settings_precedence : SettingsPrecedence = SettingsPrecedence.User,
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
        :class:`SubtitleBatcher`. Has no effect when resuming an existing project.
    settings_precedence : SettingsPrecedence, optional
        Controls how saved project settings are merged with caller-supplied *settings* when
        resuming an existing `.subtrans` project.

    Returns
    -------
    SubtitleProject
        The initialized subtitle project.

    Notes
    -----
    Subtitles are preprocessed and batched using the supplied settings or default values.
    When resuming an existing project, preprocessing and batching are skipped.

    Examples
    --------

    # Create a minimal project
    project = init_project(filepath="movie.srt")

    # Create a project and translate it with a translator
    options = init_options("target_language": "Spanish", provider="OpenAI", model="gpt-5-mini", api_key="sk-   ")
    project = init_project(options, filepath="movie.srt")
    translator = init_translator(options)
    project.TranslateSubtitles(translator)

    # Create a persistent project
    project = init_project(options, filepath="movie.srt", persistent=True)
    project.SaveProject()
    """
    project = SubtitleProject(persistent=persistent)

    settings = SettingsType(settings or {})

    normalised_path = GetInputPath(filepath)

    if normalised_path:
        project.InitialiseProject(normalised_path)

        if project.existing_project:
            project_settings = project.GetProjectSettings()
            if settings_precedence == SettingsPrecedence.Project:
                # Project settings win over caller-supplied values
                settings.update(project_settings)
            else:
                # User precedence: project settings only fill keys the caller did not supply
                settings.update({k: v for k, v in project_settings.items() if k not in settings})

        if settings:
            project.UpdateProjectSettings(settings)

        subtitles = project.subtitles

        if not subtitles or not subtitles.originals:
            raise SubtitleError(f"No subtitles were loaded from '{normalised_path}'")

        if not project.existing_project:
            # Resumed projects already contain synchronised scenes/batches — re-running
            # these mutators would desync originals from translated and break resumption.
            options = Options(settings)
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
    'SettingsPrecedence',
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
    'init_translation_provider',
    'init_translator',
    'preprocess_subtitles',
]
