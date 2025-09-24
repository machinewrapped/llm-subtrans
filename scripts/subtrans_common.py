import os
import logging

from argparse import ArgumentParser, Namespace
from dataclasses import dataclass

from PySubtrans.Helpers import GetOutputPath
from PySubtrans.Helpers.Localization import _
from PySubtrans.Helpers.Parse import ParseNames
from PySubtrans import batch_subtitles, preprocess_subtitles, init_options
from PySubtrans.Options import Options, config_dir
from PySubtrans.Substitutions import Substitutions
from PySubtrans.SubtitleFormatRegistry import SubtitleFormatRegistry
from PySubtrans.SubtitleProject import SubtitleProject

@dataclass
class LoggerOptions():
    file_handler: logging.FileHandler|None
    log_path: str

def InitLogger(logfilename: str, debug: bool = False) -> LoggerOptions:
    """ Initialise the logger with a file handler and return the path to the log file """
    log_path = os.path.join(config_dir, f"{logfilename}.log")
    file_handler = None

    if debug:
        logging_level = logging.DEBUG
    else:
        level_name = os.getenv('LOG_LEVEL', 'INFO').upper()
        logging_level = getattr(logging, level_name, logging.INFO)

    # Create console logger
    try:
        logging.basicConfig(format='%(levelname)s: %(message)s', encoding='utf-8', level=logging_level)
        logging.info("Initialising log")

    except Exception as e:
        logging.basicConfig(format='%(levelname)s: %(message)s', level=logging_level)
        logging.info("Unable to write to utf-8 log, falling back to default encoding")

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
    parser.add_argument('--scenethreshold', type=float, default=None, help="Number of seconds between lines to consider a new scene")
    parser.add_argument('--substitution', action='append', type=str, default=None, help="A pair of strings separated by ::, to subsitute in source or translation")
    parser.add_argument('--temperature', type=float, default=0.0, help="A higher temperature increases the random variance of translations.")
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
        'scene_threshold': args.scenethreshold,
        'substitutions': Substitutions.Parse(args.substitution),
        'target_language': args.target_language,
        'temperature': args.temperature,
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

