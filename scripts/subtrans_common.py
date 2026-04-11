import os
import logging
import sys

from argparse import ArgumentParser, Namespace
from contextlib import contextmanager
from dataclasses import dataclass, field

from PySubtrans.Helpers import GetOutputPath
from PySubtrans.Helpers.Localization import _
from PySubtrans.Helpers.Parse import ParseNames
from PySubtrans import batch_subtitles, init_options, init_translator, preprocess_subtitles
from PySubtrans.Options import Options, config_dir
from PySubtrans.SubtitleTranslator import SubtitleTranslator
from PySubtrans.Substitutions import Substitutions
from PySubtrans.SubtitleFormatRegistry import SubtitleFormatRegistry
from PySubtrans.SubtitleProject import SubtitleProject

@dataclass
class LoggerOptions():
    file_handler: logging.FileHandler|None
    log_path: str


@dataclass
class TokenUsage():
    """Accumulated token usage across all translated batches."""
    prompt_tokens: int = field(default=0)
    output_tokens: int = field(default=0)

    def add(self, content : dict) -> None:
        """Add token counts from a translation response content dict."""
        self.prompt_tokens += content.get('prompt_tokens') or 0
        self.output_tokens += content.get('output_tokens') or 0

    @property
    def has_data(self) -> bool:
        return self.prompt_tokens > 0 or self.output_tokens > 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.output_tokens


class TranslationProgressLogger():
    """
    Connects to SubtitleTranslator events and logs batch-level progress to the console.

    Attach before calling TranslateSubtitles and detach (or use the context manager)
    afterwards so that the event subscriptions are cleaned up properly.
    """

    def __init__(self, verbose : bool = False) -> None:
        self._verbose = verbose
        self._total_lines : int = 0
        self._processed_lines : int = 0
        self.token_usage : TokenUsage = TokenUsage()

    @contextmanager
    def track(self, translator : SubtitleTranslator):
        """Context manager that attaches/detaches progress tracking around a translation."""
        self._attach(translator)
        try:
            yield self
        finally:
            self._detach(translator)

    def _attach(self, translator : SubtitleTranslator) -> None:
        self._total_lines = 0
        self._processed_lines = 0
        self.token_usage = TokenUsage()
        translator.events.preprocessed.connect(self._on_preprocessed)
        translator.events.batch_translated.connect(self._on_batch_translated)

    def _detach(self, translator : SubtitleTranslator) -> None:
        translator.events.preprocessed.disconnect(self._on_preprocessed)
        translator.events.batch_translated.disconnect(self._on_batch_translated)

    def _on_preprocessed(self, _sender, scenes : list) -> None:
        self._total_lines = sum(scene.linecount for scene in scenes)

    def _on_batch_translated(self, _sender, batch) -> None:
        self._processed_lines += batch.size
        label = f"{batch.scene}.{batch.number}"

        pct = f"{100 * self._processed_lines // self._total_lines}%" if self._total_lines else ""
        progress = f"{self._processed_lines}/{self._total_lines} lines{f' ({pct})' if pct else ''}"

        if self._verbose and batch.translation:
            content = batch.translation.content
            prompt = content.get('prompt_tokens') or 0
            output = content.get('output_tokens') or 0
            token_info = f" [{prompt} in / {output} out tokens]"
            self.token_usage.add(content)
        else:
            token_info = ""
            if batch.translation:
                self.token_usage.add(batch.translation.content)

        logging.info("Translated batch %s: %s%s", label, progress, token_info)

def InitLogger(logfilename: str, debug: bool = False) -> LoggerOptions:
    """ Initialise the logger with a file handler and return the path to the log file """
    log_path = os.path.join(config_dir, f"{logfilename}.log")
    file_handler = None

    if debug:
        logging_level = logging.DEBUG
    else:
        level_name = os.getenv('LOG_LEVEL', 'INFO').upper()
        logging_level = getattr(logging, level_name, logging.INFO)

    # Configure the root logger level and add a console handler unconditionally.
    # logging.basicConfig() is a no-op when handlers already exist (e.g. because an
    # imported SDK such as google.genai or openai added one during import), so we
    # set up the StreamHandler explicitly instead.
    root_logger = logging.getLogger()
    root_logger.setLevel(logging_level)

    try:
        console_handler = logging.StreamHandler()
        console_handler.stream = open(sys.stderr.fileno(), mode='w', encoding='utf-8', closefd=False)
        init_message = "Initialising log"
    except Exception:
        console_handler = logging.StreamHandler()
        init_message = "Unable to write to utf-8 log, falling back to default encoding"

    console_handler.setLevel(logging_level)
    console_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
    root_logger.addHandler(console_handler)

    logging.info(init_message)

    if debug:
        logging.debug("Debug logging enabled")

    # Create file handler with the same logging level
    try:
        os.makedirs(config_dir, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding='utf-8', mode='w')
        file_handler.setLevel(logging_level)
        formatter = logging.Formatter('%(levelname)s: %(message)s')
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.INFO)
        logging.getLogger('').addHandler(file_handler)
    except Exception as e:
        logging.warning(f"Unable to create log file at {log_path}: {e}")

    return LoggerOptions(file_handler=file_handler, log_path=log_path)

def CreateArgParser(description : str) -> ArgumentParser:
    """
    Create new arg parser and parse shared command line arguments between models
    """
    pre_parser = ArgumentParser(add_help=False)
    pre_parser.add_argument('--list-formats', action='store_true')
    pre_args, _ = pre_parser.parse_known_args()
    if pre_args.list_formats:
        HandleFormatListing(pre_args)
        
    parser = ArgumentParser(description=description)
    input_help = "Path to subtitle file (see --list-formats for supported formats)"
    parser.add_argument('input', help=input_help)
    parser.add_argument('-o', '--output', help="Output subtitle file path; format inferred from extension")
    parser.add_argument('--list-formats', action='store_true', help="List supported subtitle formats and exit")
    parser.add_argument('-l', '--target_language', type=str, default=None, help="The target language for the translation")
    parser.add_argument('--batchthreshold', type=float, default=None, help="Number of seconds between lines to consider for batching")
    parser.add_argument('--debug', action='store_true', help="Run with DEBUG log level")
    parser.add_argument('--verbose', action='store_true', help="Log detailed progress and token usage for each batch")
    parser.add_argument('--description', type=str, default=None, help="A brief description of the film to give context")
    parser.add_argument('--addrtlmarkers', action='store_true', help="Add RTL markers to translated lines if they contains primarily right-to-left script")
    parser.add_argument('--includeoriginal', action='store_true', help="Include the original text in the translated subtitles")
    parser.add_argument('--instruction', action='append', type=str, default=None, help="An instruction for the AI translator")
    parser.add_argument('--instructionfile', type=str, default=None, help="Name/path of a file to load instructions from")
    parser.add_argument('--matchpartialwords', action='store_true', help="Allow substitutions that do not match not on word boundaries")
    parser.add_argument('--maxbatchsize', type=int, default=None, help="Maximum number of lines before starting a new batch is compulsory")
    parser.add_argument('--maxlines', type=int, default=None, help="Maximum number of lines(subtitles) to process in this run")
    parser.add_argument('--maxsummaries', type=int, default=None, help="Maximum number of context summaries to provide with each batch")
    parser.add_argument('--minbatchsize', type=int, default=None, help="Minimum number of lines to consider starting a new batch")
    parser.add_argument('--moviename', type=str, default=None, help="Optionally specify the name of the movie to help the translator")
    parser.add_argument('--name', action='append', type=str, default=None, help="A name to use verbatim in the translation")
    parser.add_argument('--names', type=str, default=None, help="A list of names to use verbatim")
    parser.add_argument('--postprocess', action='store_true', default=None, help="Postprocess the subtitles after translation")
    parser.add_argument('--preprocess', action='store_true', default=None, help="Preprocess the subtitles before translation")
    parser.add_argument('--project', action='store_true', help="Create a persistent project file to allow resuming translation")
    parser.add_argument('--preview', action='store_true', help="Create a project and preview the translation flow without calling the translation provider")
    parser.add_argument('--retranslate', action='store_true', help="Retranslate all subtitles, ignoring existing translations in the project file")
    parser.add_argument('--reparse', action='store_true', help="Reparse previous translation responses, reconstructing the translated subtitles")
    parser.add_argument('--reload', action='store_true', help="Reload the subtitles from the original file, ignoring existing subtitles in the project file")
    parser.add_argument('--ratelimit', type=int, default=None, help="Maximum number of batches per minute to process")
    parser.add_argument('--proxy', type=str, default=None, help="Proxy URL (e.g., http://127.0.0.1:8888 or socks5://127.0.0.1:1080)")
    parser.add_argument('--proxycert', type=str, default=None, help="Path to a custom certificate bundle (PEM) to use for SSL verification")
    parser.add_argument('--scenethreshold', type=float, default=None, help="Number of seconds between lines to consider a new scene")
    parser.add_argument('--substitution', action='append', type=str, default=None, help="A pair of strings separated by ::, to subsitute in source or translation")
    parser.add_argument('--temperature', type=float, default=0.0, help="A higher temperature increases the random variance of translations.")
    parser.add_argument('--autosplit', action='store_true', default=None, help="Split batches that fail validation in half and retry each half separately")
    parser.add_argument('--writebackup', action='store_true', help="Write a backup of the project file when it is loaded (if it exists)")
    return parser

def HandleFormatListing(args: Namespace) -> None:
    """Print supported subtitle formats and exit if requested."""
    if getattr(args, "list_formats", False):
        formats = SubtitleFormatRegistry.list_available_formats()
        if formats:
            print(f"Supported subtitle formats: {formats}")
        else:
            print("No subtitle formats available.")
        raise SystemExit(0)

def CreateOptions(args: Namespace, provider: str, **kwargs) -> Options:
    """ Create options with additional arguments """
    if getattr(args, 'proxycert', None):
        os.environ['SSL_CERT_FILE'] = args.proxycert
        logging.info(f"Using custom SSL certificate bundle: {args.proxycert}")

    settings = {
        'api_key': args.apikey,
        'description': args.description,
        'include_original': args.includeoriginal,
        'add_right_to_left_markers': args.addrtlmarkers,
        'instruction_args': args.instruction,
        'instruction_file': args.instructionfile or "instructions.txt",
        'substitution_mode': "Partial Words" if args.matchpartialwords else "Auto",
        'max_batch_size': args.maxbatchsize,
        'max_context_summaries': args.maxsummaries,
        'max_lines': args.maxlines,
        'min_batch_size': args.minbatchsize,
        'movie_name': args.moviename or os.path.splitext(os.path.basename(args.input))[0],
        'names': ParseNames(args.names or args.name),
        'postprocess_translation': args.postprocess,
        'preprocess_subtitles': args.preprocess,
        'project_file': args.project or args.reparse or args.retranslate or args.reload,
        'preview': args.preview,
        'reparse': args.reparse,
        'retranslate': args.retranslate,
        'reload': args.reload,
        'rate_limit': args.ratelimit,
        'proxy': getattr(args, 'proxy', None),
        'scene_threshold': args.scenethreshold,
        'substitutions': Substitutions.Parse(args.substitution),
        'target_language': args.target_language,
        'temperature': args.temperature,
        'autosplit_on_error': args.autosplit,
        'write_backup': args.writebackup,
    }

    # Adding optional new keys from kwargs
    settings.update(kwargs)

    # Use PySubtrans init_options for proper instruction file handling
    return init_options(provider=provider, **settings)

def CreateProject(options : Options, args: Namespace) -> SubtitleProject:
    """
    Initialise a subtitle project with the provided arguments
    """
    project = SubtitleProject(persistent=options.use_project_file)

    project.InitialiseProject(args.input, args.output)

    if args.writebackup and project.existing_project:
        logging.info("Saving backup copy of the project")
        project.SaveBackupFile()

    project.UpdateProjectSettings(options)

    subtitles = project.subtitles

    if not subtitles or not subtitles.originals:
        raise ValueError(_("Subtitle file contains no translatable content"))

    if options.get_bool('preprocess_subtitles'):
        preprocess_subtitles(subtitles, options)

    scene_threshold = options.get_float('scene_threshold')
    min_batch_size = options.get_int('min_batch_size')
    max_batch_size = options.get_int('max_batch_size')

    missing_params = [
        name for name, value in (
            ("scene_threshold", scene_threshold),
            ("min_batch_size", min_batch_size),
            ("max_batch_size", max_batch_size),
        ) if not value # 0 is not valid for any of these
    ]

    if missing_params:
        raise ValueError(f"The following parameter(s) must be defined: {', '.join(missing_params)}")

    if scene_threshold and min_batch_size and max_batch_size:
        batch_subtitles(
            subtitles,
            scene_threshold=scene_threshold,
            min_batch_size=min_batch_size,
            max_batch_size=max_batch_size,
        )

    scene_count = subtitles.scenecount
    if scene_count < 1:
        raise ValueError(_("No scenes were created from the subtitles"))

    batch_count = sum(len(scene.batches) for scene in subtitles.scenes)
    logging.info(f"Created {scene_count} scenes and {batch_count} batches for translation")

    if not args.output:
        output_path = GetOutputPath(project.subtitles.sourcepath, project.target_language or options.provider, project.subtitles.file_format)
        if output_path:
            project.subtitles.outputpath = output_path

    logging.info(f"Translating {project.subtitles.linecount} subtitles from {project.subtitles.sourcepath}")
    logging.info(f"Output path will be: {project.subtitles.outputpath}")

    return project

def LogTranslationStatus(project : SubtitleProject, preview : bool = False, has_error : bool = False, token_usage : TokenUsage|None = None) -> None:
    """Log a clear completion summary for the translation run."""
    subtitles = project.subtitles
    if not subtitles:
        logging.error("Translation status: no subtitles loaded")
        return

    total_lines : int = subtitles.linecount
    translated_lines : int = len(subtitles.translated) if subtitles.translated else 0

    if has_error:
        if preview:
            logging.error("Translation status: preview failed")
        elif translated_lines > 0:
            logging.warning(f"Translation status: failed after partial progress ({translated_lines}/{total_lines} lines translated)")
        else:
            logging.error(f"Translation status: failed (0/{total_lines} lines translated)")
        return

    if preview:
        logging.info("Translation status: preview completed (no translation was requested)")
        return

    if project.all_translated:
        logging.info(f"Translation status: completed ({translated_lines}/{total_lines} lines translated)")
    elif translated_lines > 0:
        logging.warning(f"Translation status: incomplete ({translated_lines}/{total_lines} lines translated)")
    else:
        logging.error(f"Translation status: failed (0/{total_lines} lines translated)")

    if token_usage and token_usage.has_data:
        logging.info(f"Token usage: {token_usage.prompt_tokens} in / {token_usage.output_tokens} out ({token_usage.total_tokens} total)")

def TranslateProject(project : SubtitleProject, options : Options, verbose : bool = False, preview : bool = False) -> None:
    """
    Translate a prepared project, logging progress and final status.

    Creates the translator, attaches progress tracking, runs the translation,
    saves the project file if needed, and logs the completion status.
    Callers only need to handle errors raised before the project is ready.
    """
    progress_logger : TranslationProgressLogger = TranslationProgressLogger(verbose=verbose)
    translator : SubtitleTranslator = init_translator(options)

    try:
        with progress_logger.track(translator):
            project.TranslateSubtitles(translator)

        if project.use_project_file:
            project.UpdateProjectFile()

        LogTranslationStatus(project, preview=preview, token_usage=progress_logger.token_usage)

    except Exception:
        LogTranslationStatus(project, preview=preview, has_error=True, token_usage=progress_logger.token_usage)
        raise

