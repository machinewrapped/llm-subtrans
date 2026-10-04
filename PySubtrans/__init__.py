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
subs.SaveTranslation("movie_translated.srt", save_settings=SaveSettings(opts))

Transcribing Media
------------------

# Create a transcriber with its own provider settings (requires ffmpeg)
transcriber = init_transcription(provider="OpenRouter", api_key="sk-or-...", language="Japanese")

# Transcribe the media into subtitles, batched for translation using the translation options
subs, error = transcribe_media(transcriber, "movie.mkv", options=opts)

# Save the transcription, then translate it as above
subs.SaveOriginal("movie.ja.vtt")
translator.TranslateSubtitles(subs)
"""
from __future__ import annotations

from collections.abc import Mapping
from enum import Enum

from PySubtrans.Helpers import GetInputPath
from PySubtrans.Helpers.InstructionsHelpers import LoadInstructions
from PySubtrans.Helpers.Localization import _
from PySubtrans.Options import Options
from PySubtrans.SettingsType import SettingType, SettingsType
from PySubtrans.SubtitleBatcher import SubtitleBatcher
from PySubtrans.SubtitleBuilder import SubtitleBuilder
from PySubtrans.SubtitleEditor import SubtitleEditor
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.SubtitleFormatRegistry import SubtitleFormatRegistry
from PySubtrans.SubtitleLine import SubtitleLine
from PySubtrans.Subtitles import OriginalTextPlacement, SaveSettings, Subtitles
from PySubtrans.SubtitleProcessor import SubtitleProcessor
from PySubtrans.SubtitleProject import SubtitleProject
from PySubtrans.SubtitleScene import SubtitleScene
from PySubtrans.SubtitleTranslator import SubtitleTranslator
from PySubtrans.Transcription.AudioChunker import AudioChunker
from PySubtrans.Transcription.TranscriptionCoordinator import TranscriptionCoordinator
from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider
from PySubtrans.TranslationProvider import TranslationProvider
from PySubtrans.version import __version__

# Settings the transcriber takes from Options when they are not supplied.
# Transcribed lines obey the same limits as loaded and translated subtitles.
# A whole Options is not passed on, because its translation defaults (e.g. max_retries) would override the provider's own.
_TRANSCRIPTION_OPTIONS : list[str] = [
    'max_characters',
    'max_line_duration',
    'min_line_duration',
    'min_split_chars',
    'max_newlines',
    'min_gap',
    'abbreviations',
    'ffmpeg_path',
]


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
        build_terminology_map = True,

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
        _batch_with_options(subtitles, options)

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
    terminology_map : dict[str,str]|None = None,
) -> SubtitleTranslator:
    """
    Return a ready-to-use :class:`SubtitleTranslator` using the specified settings.

    Parameters
    ----------
    settings : Options or SettingsType
        The translator settings. This should specify the provider and model to use, along with extra configuration options as needed.
    translation_provider : TranslationProvider or None, optional
        An pre-configured :class:`TranslationProvider` instance (if not specified a provider is created automatically based on the settings).
    terminology_map : dict[str, str] or None, optional
        Seed terminology map used to guide consistent term translation.  The translator builds on this map as translation proceeds;
        subscribe to the ``terminology_updated`` event to receive snapshots after each batch.

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

    # Create translator from a plain dictionary
    translator = init_translator({"provider": "gemini", "api_key": "your-key", "model": "gemini-flash-latest"})

    # Create translator with a terminology seed
    translator = init_translator(opts, terminology_map={"Dragon": "Drache", "Hero": "Held"})

    # Create translator with a pre-initialised TranslationProvider
    provider = init_translation_provider("OpenAI", {"model": "gpt-5-mini", "api_key": "sk-..."})
    options = init_options(prompt="Translate these subtitles into Spanish")
    translator = init_translator(options, translation_provider=provider)

    # Subscribe to events (see TranslationEvents for full list):
    #   batch_translated, scene_translated, batch_updated, preprocessed
    #   terminology_updated  -- fired after each batch when build_terminology_map=True
    #   translation_cost     -- fired after each provider response reports a cost
    #   error, warning, info
    """
    options = Options(settings)

    translation_provider = translation_provider or TranslationProvider.get_provider(options)

    if not translation_provider.ValidateSettings():
        message = translation_provider.validation_message or f"Invalid settings for provider {options.provider}"
        raise SubtitleError(message)

    options.provider = translation_provider.name

    return SubtitleTranslator(options, translation_provider, terminology_map=terminology_map)


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
                _batch_with_options(subtitles, options)

    project.save_settings = SaveSettings(Options(settings))

    return project


def init_transcription_provider(provider : str, **settings : SettingType) -> TranscriptionProvider:
    """
    Initialise and validate a :class:`TranscriptionProvider` instance.

    Parameters
    ----------
    provider : str
        The transcription provider name, e.g. "OpenRouter", "OpenAI", "Gemini", "Qwen Local".
    **settings : SettingType
        Provider settings such as `model`, `api_key`, `server_address` or `language`.
        Settings that are None are ignored, so the provider's defaults apply.

    Returns
    -------
    TranscriptionProvider
        A provider instance with validated settings.

    Examples
    --------

    provider = init_transcription_provider("OpenAI", api_key="sk-...", model="whisper-1")
    transcriber = init_transcription(provider)
    """
    if not provider:
        raise SubtitleError(_("Transcription provider name is required"))

    provider_settings = SettingsType({key: value for key, value in settings.items() if value is not None})

    try:
        transcription_provider = TranscriptionProvider.create_provider(provider, provider_settings)
    except ValueError as exc:
        raise SubtitleError(str(exc)) from exc

    _validate_transcription_provider(transcription_provider)

    return transcription_provider


def init_transcription(
    provider : str|TranscriptionProvider,
    *,
    model : str|None = None,
    api_key : str|None = None,
    language : str|None = None,
    diarize : bool|None = None,
    **settings : SettingType,
) -> TranscriptionCoordinator:
    """
    Return a :class:`TranscriptionCoordinator` ready to transcribe media with the specified provider.

    Transcription settings are separate from translation settings, so the transcription and translation providers can differ.

    Parameters
    ----------
    provider : str or TranscriptionProvider
        The transcription provider name, or a provider created with :func:`init_transcription_provider`.
        "OpenRouter" is recommended: its default model, microsoft/mai-transcribe-2, gives the best results.
    model : str or None, optional
        The transcription model. Defaults to the provider's recommended model.
    api_key : str or None, optional
        The API key for the provider, if it needs one.
    language : str or None, optional
        The spoken language, e.g. "Japanese" or "ja". When omitted the provider detects the language.
    diarize : bool or None, optional
        Identify speakers, which helps prevent lines spoken by different people from being merged into one subtitle.
        On by default for providers that support it; pass False to turn it off.
    **settings : SettingType
        Additional settings, e.g.

        server_address = "http://localhost:8000/v1",
        audio_track = 1,
        ffmpeg_path = "/usr/local/bin/ffmpeg",
        max_characters = 80,
        max_line_duration = 5.0,
        postprocess_transcription = True,

        Line limits not specified are taken from the :class:`Options` defaults.
        When *provider* is an instance, `model`, `api_key` and provider-specific settings are not applied to it.

    Exceptions
    ----------
    SubtitleError
        If the provider is unknown, its settings are invalid or the language is not recognised.

    Returns
    -------
    TranscriptionCoordinator
        A transcriber to pass to :func:`transcribe_media`.
        Subscribe to its `events` for progress (see :class:`TranscriptionEvents`).

    Examples
    --------

    transcriber = init_transcription("OpenRouter", api_key="sk-or-...", language="Japanese")

    # Local transcription with Qwen3-ASR (requires torch and qwen-asr to be installed)
    transcriber = init_transcription("Qwen Local", language="Chinese")
    """
    explicit_settings = {'model': model, 'api_key': api_key, 'language': language, 'diarize': diarize, **settings}
    explicit_settings = SettingsType({key: value for key, value in explicit_settings.items() if value is not None})

    if isinstance(provider, TranscriptionProvider):
        transcription_provider = provider
        _validate_transcription_provider(transcription_provider)
    else:
        transcription_provider = init_transcription_provider(provider, **explicit_settings)

    options = Options(explicit_settings)

    coordinator_settings = SettingsType(explicit_settings)
    for key in _TRANSCRIPTION_OPTIONS:
        if key not in coordinator_settings:
            coordinator_settings[key] = options.get(key)

    # The provider converts the language hint to the form its engine expects
    language_hint = language or transcription_provider.settings.get_str('language')
    coordinator_settings['language'] = transcription_provider.ResolveLanguageCode(language_hint, options.ui_language)

    # Chunk bounds given for this run override the provider's
    min_chunk_seconds = coordinator_settings.get_float('min_chunk_seconds') or transcription_provider.settings.get_float('min_chunk_seconds')
    max_chunk_seconds = coordinator_settings.get_float('max_chunk_seconds') or transcription_provider.settings.get_float('max_chunk_seconds')
    if min_chunk_seconds is not None and max_chunk_seconds is not None:
        AudioChunker.ValidateChunkBounds(min_chunk_seconds, max_chunk_seconds)

    return TranscriptionCoordinator(transcription_provider, coordinator_settings)


def transcribe_media(
    transcriber : TranscriptionCoordinator,
    media_path : str,
    *,
    options : Options|SettingsType|None = None,
    auto_batch : bool = True,
) -> tuple[Subtitles, SubtitleError|None]:
    """
    Transcribe a media file into :class:`Subtitles` ready for translation.

    This call blocks until the transcription finishes, which can take a long time for a full-length video.

    Parameters
    ----------
    transcriber : TranscriptionCoordinator
        A transcriber created with :func:`init_transcription`.
    media_path : str
        Path to the video or audio file to transcribe.
    options : Options or SettingsType, optional
        Settings for post-processing and batching the transcribed lines, e.g. `remove_filler_words`, `scene_threshold`, `max_batch_size`.
        Defaults to the settings the transcriber was created with.
    auto_batch : bool, optional
        If True (default), divide the subtitles into scenes and batches ready for translation.

    Returns
    -------
    tuple[Subtitles, SubtitleError or None]
        The transcribed subtitles, and the error that stopped the transcription early, if any.
        Lines transcribed before an error are returned so they are not lost.
        Pass them to `transcriber.CreateTranscription` as `prior_subtitles` to resume.

    Exceptions
    ----------
    SubtitleError
        If no subtitles could be transcribed.

    Examples
    --------

    subs, error = transcribe_media(transcriber, "movie.mkv")
    if error:
        print(f"Transcription is incomplete: {error}")
    """
    options = Options(options or transcriber.settings)

    outcome = transcriber.CreateTranscription(media_path, options)

    subtitles = outcome.subtitles
    if subtitles is None or not subtitles.originals:
        raise outcome.error or SubtitleError(_("No subtitles were transcribed from '{}'").format(media_path))

    if auto_batch:
        _batch_with_options(subtitles, options)

    return subtitles, outcome.error


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
    min_gap : float = 0.05,
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
    min_gap : float, optional
        Minimum gap in seconds to preserve when preventing overlaps.

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
        'min_gap': min_gap,
    }))

    with SubtitleEditor(subtitles) as editor:
        editor.AutoBatch(batcher)

    return subtitles.scenes


def _batch_with_options(subtitles : Subtitles, options : Options) -> None:
    """Divide subtitles into scenes and batches using the batching settings in *options*."""
    batch_subtitles(
        subtitles,
        scene_threshold=options.get_float('scene_threshold') or 60.0,
        min_batch_size=options.get_int('min_batch_size') or 1,
        max_batch_size=options.get_int('max_batch_size') or 100,
        prevent_overlap=options.get_bool('prevent_overlapping_times'),
        min_gap=options.get_float('min_gap', 0.05) or 0.0,
    )


def _validate_transcription_provider(provider : TranscriptionProvider) -> None:
    """Raise a SubtitleError explaining why the provider's settings are invalid."""
    if not provider.ValidateSettings():
        message = provider.validation_message or _("Invalid settings for transcription provider {}").format(provider.name)
        raise SubtitleError(message)


__all__ = [
    '__version__',
    'Options',
    'OriginalTextPlacement',
    'SaveSettings',
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
    'TranscriptionCoordinator',
    'TranscriptionProvider',
    'TranslationProvider',
    'init_options',
    'batch_subtitles',
    'init_project',
    'init_subtitles',
    'init_transcription',
    'init_transcription_provider',
    'init_translation_provider',
    'init_translator',
    'preprocess_subtitles',
    'transcribe_media',
]
