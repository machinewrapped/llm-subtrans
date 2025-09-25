"""Batch translate subtitle files using PySubtrans.

Processes all subtitle files in a source directory and writes translated versions to a destination
directory. The script also serves as a self-contained example of a full translation workflow using
PySubtrans.

QUICK START:
1. Set your provider and API key (see options below)
2. Run: python scripts/batch-translate.py source_dir output_dir

Important options:
- source_path: Directory containing subtitle files to translate
- destination_path: Directory to write translated subtitle files
- provider: Translation service (required - e.g. "OpenRouter", "Gemini")
- api_key: Your API key for the selected provider
- model: Specific model to use
- target_language: The language subtitles should be translated into
- prompt: A more specific prompt to give the translator (e.g. "Translate these subtitles into French and make them funny")
- instruction_file: Path to a file containing detailed custom instructions for the translator
- output_format: (optionally) write all translated subtitles using a specific file format (e.g. ".srt")
- preview: Exercise the workflow without making any API calls to the translation provider

Options can be specified by:
- Passing command line arguments
- Editing DEFAULT_OPTIONS in this script
- Via environment variables (e.g. OPENROUTER_API_KEY=sk-...) or a .env file
- Any combination of the above, in order of precedence

EXAMPLES:
    # Minimal: assumes most settings are configured in the script or environment
    python scripts/batch-translate.py ./subtitles ./translated --prompt "Translate these subtitles into Spanish"

    # With provider and model overrides on the command line
    python scripts/batch-translate.py ./subtitles ./translated --language="French" \\
        --provider="OpenAI" --model="gpt-5-mini" --apikey="sk-..."

There are many more options available, some of which are provider-specific. 
See Options.py or the documentation at https://github.com/machinewrapped/llm-subtrans/ for more details.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import logging
import pathlib
import sys

from PySubtrans import init_options, init_subtitles, init_translator, init_translation_provider
from PySubtrans import Options, SettingsType, SubtitleError
from PySubtrans import SubtitleTranslator
from PySubtrans import TranslationProvider
from PySubtrans import SubtitleFormatRegistry

from PySubtrans.Helpers import GetOutputPath
from PySubtrans.SettingsType import redact_sensitive_values

# Default configuration options for batch processing.
# These can be overridden by command line arguments.
# Any unspecified options will use PySubtrans defaults.
# Some providers may require additional options to be set (e.g. server_address, use_default_model).
DEFAULT_OPTIONS = SettingsType({
    'source_path': './subtitles',
    'destination_path': './translated',
    'target_language': 'English',                   # The language to translate subtitles to
    'output_format': None,                          # Optional format override, e.g. "srt". If not specified, inferred from source file.
    'provider': "OpenRouter",                       # Translation provider to use, e.g. "Gemini"
    'api_key': None,                                # Your API key for the selected provider
    'model': "x-ai/grok-4-fast:free",               # Your preferred model name
    'prompt': 'Translate these subtitles into [target_language]',       # High level prompt template
    'instruction_file': 'instructions.txt',         # Optional file containing detailed instructions
    'scene_threshold': 60.0,                        # Scene detection threshold in seconds
    'max_batch_size': 100,                          # Maximum number of lines to include in each translation batch
    'preprocess_subtitles': True,                   # Whether to apply preprocessing steps to the subtitles before translation
    'postprocess_translation': True,                # Whether to apply postprocessing steps to the translated subtitles
    'log_path': './batch-translate.log',
    'preview': False,                               # Set to True to exercise the workflow without calling the API to execute translations.
})

class BatchJobConfig:
    """
    Container for batch translation configuration
    """
    def __init__(self, options : Options):
        """
        Initialize the batch job configuration with PySubtrans options.
        """
        self.options = options

        self.source_path = self.options.get_str('source_path') or './subtitles'
        self.destination_path = self.options.get_str('destination_path') or './translated'
        self.log_path = self.options.get_str('log_path') or './batch_translate.log'
        self.output_format = self.options.get_str('output_format')
        self.target_language = self.options.get_str('target_language')
        self.prompt = self.options.get_str('prompt')
        self.provider = self.options.get_str('provider')
        self.model = self.options.get_str('model')
        self.instruction_file = self.options.get_str('instruction_file')

class BatchProcessor:
    """Coordinate discovery and translation of subtitle files."""

    def __init__(self, config : BatchJobConfig):
        self.config = config
        self.options = config.options
        self.logger = logging.getLogger(__name__)
        self.progress_display = ProgressDisplay()
        self.translation_provider = self._initialise_provider()

    def run(self) -> BatchStatistics:
        """Execute the batch translation workflow."""
        source_root = pathlib.Path(self.config.source_path).expanduser().resolve()
        if not source_root.exists() or not source_root.is_dir():
            raise SubtitleError(f"Source path '{source_root}' does not exist or is not a directory")

        destination_root = pathlib.Path(self.config.destination_path).expanduser().resolve()
        destination_root.mkdir(parents=True, exist_ok=True)

        self.logger.info("Starting batch translation from %s", source_root)
        self.logger.info("Writing translated files to %s", destination_root)
        self.logger.info("Using provider: %s with model: %s", self.translation_provider.name, self.translation_provider.selected_model or "default")
        self.logger.info("Prompt: %s", self.config.prompt)

        if self.config.instruction_file:
            self.logger.info("Instructions file: %s", self.config.instruction_file)

        if self.config.target_language:
            self.logger.info("Target language: %s", self.config.target_language)

        if self.config.output_format is not None:
            self.logger.info("Output format: %s", self.config.output_format)

        # Ask PySubtrans for the list of recognised subtitle formats so our
        # discovery step only picks up files the library knows how to parse.
        supported_extensions = {ext.lower() for ext in SubtitleFormatRegistry.enumerate_formats()}
        self.logger.info("Supported subtitle formats: %s", ", ".join(sorted(supported_extensions)))

        files = self._discover_files(source_root, supported_extensions, destination_root)
        stats = BatchStatistics(discovered_files=len(files))

        if not files:
            self.logger.warning("No subtitle files found in %s", source_root)
            return stats

        self.logger.info("Translating %d subtitle file(s) from %s to %s", len(files), source_root, destination_root)

        for index, source_file in enumerate(files, start=1):
            relative_name = source_file.relative_to(source_root)
            output_base = destination_root / relative_name

            self.logger.info("[%d/%d] Loading %s", index, len(files), source_file)

            try:
                # init_subtitles loads and batches the file using the Options we prepared earlier.
                subtitles = init_subtitles(filepath=str(source_file), options=self.options)

            except SubtitleError as exc:
                self.logger.error("Failed to load %s: %s", source_file, exc)
                stats.failed_files += 1
                continue

            self.logger.debug("Detected format %s", subtitles.file_format or "unknown")

            try:
                # Determine the final output path so language suffixes and format overrides are applied consistently.
                destination_file = self._prepare_destination(output_base, subtitles.file_format)

            except SubtitleError as exc:
                self.logger.error("Unable to determine output path for %s: %s", source_file, exc)
                stats.failed_files += 1
                continue

            if not self.options.get_bool('preview') and destination_file.exists():
                self.logger.info("Skipping %s because %s already exists", source_file, destination_file)
                stats.skipped_files += 1
                continue

            try:
                # init_translator builds a ready-to-use SubtitleTranslator
                # configured with our provider and processing settings.
                translator = init_translator(self.options, translation_provider=self.translation_provider)

            except SubtitleError as exc:
                raise SubtitleError(f"Unable to initialise translator: {exc}") from exc

            # ProgressDisplay.track hooks into SubtitleTranslator events to provide 
            # a concise console progress indicator while the batches are being processed.
            with self.progress_display.track(translator, source_file, translator.preview):
                try:
                    # TranslateSubtitles drives the end-to-end translation process, 
                    # raising SubtitleError if the provider reports a problem.
                    translator.TranslateSubtitles(subtitles)

                except SubtitleError as exc:
                    self.logger.error("Translation failed for %s: %s", source_file, exc)
                    stats.failed_files += 1
                    continue
                except Exception:
                    self.logger.exception("Unexpected error translating %s", source_file)
                    stats.failed_files += 1
                    continue

            if translator.preview:
                self.logger.info("Preview mode enabled - skipping save for %s", source_file)
                stats.previewed_files += 1
                continue

            try:
                # Save the translated subtitles. Format is deduced from the filename.
                subtitles.SaveTranslation(str(destination_file))

            except (SubtitleError, OSError) as exc:
                # A failure to write the result should abort the batch
                # to avoid incurring further costs if we cannot save the translations.
                raise SubtitleError(f"Failed to save translation for {source_file}: {exc}") from exc

            if translator.errors:
                self.logger.warning("Translation completed with %d error(s) for %s", len(translator.errors), source_file)

            stats.translated_files += 1
            self.logger.info("Saved translation to %s", destination_file)

        return stats

    def _discover_files(
        self,
        root : pathlib.Path,
        supported_extensions : set[str],
        exclude : pathlib.Path | None = None
    ) -> list[pathlib.Path]:
        """Return subtitle files under *root* that match supported extensions."""
        subtitle_files : list[pathlib.Path] = []
        for path in root.rglob('*'):
            if exclude:
                try:
                    if path.is_relative_to(exclude):
                        continue
                except ValueError:
                    pass
            if not path.is_file():
                continue
            if path.suffix.lower() in supported_extensions:
                subtitle_files.append(path)
        return sorted(subtitle_files)

    def _prepare_destination(self, base_output : pathlib.Path, detected_format : str|None, ) -> pathlib.Path:
        """ 
        Return a destination file path honouring configured overrides for language and format.
        """
        language = self.options.target_language or self.options.provider
        extension = self.config.output_format or detected_format

        output_path = GetOutputPath(str(base_output), language, extension)
        if not output_path:
            raise SubtitleError("Unable to determine output path")

        destination_file = pathlib.Path(output_path)
        destination_file.parent.mkdir(parents=True, exist_ok=True)
        return destination_file

    def _initialise_provider(self) -> TranslationProvider:
        """
        Create and validate a translation provider instance based on the configured options
        """
        provider_name = self.options.provider
        if not provider_name:
            raise SubtitleError("No translation provider configured. Set the 'provider' option.")

        translation_provider = init_translation_provider(provider_name, self.options)

        self.logger.debug("Validated translation provider %s", translation_provider.name)

        return translation_provider


def build_config(args : argparse.Namespace) -> BatchJobConfig:
    """Combine DEFAULT_OPTIONS with command line arguments."""
    settings = SettingsType(DEFAULT_OPTIONS)

    if args.source:
        settings['source_path'] = args.source
    if args.destination:
        settings['destination_path'] = args.destination
    if args.output_format:
        settings['output_format'] = args.output_format
    if args.log_file:
        settings['log_path'] = args.log_file

    if args.provider is not None:
        settings['provider'] = args.provider
    if args.model is not None:
        settings['model'] = args.model
    if args.api_key is not None:
        settings['api_key'] = args.api_key
    if args.prompt is not None:
        settings['prompt'] = args.prompt
    if args.target_language is not None:
        settings['target_language'] = args.target_language
    if args.instruction_file is not None:
        settings['instruction_file'] = args.instruction_file
    if args.preview is not None:
        settings['preview'] = args.preview

    for override in args.option:
        if '=' not in override:
            raise SubtitleError(f"Invalid option override '{override}', expected KEY=VALUE")
        key, value = override.split('=', 1)
        settings[key] = value

    # Initialize an Options instance with the combined settings
    options = init_options(**settings)

    return BatchJobConfig(options)

class BatchStatistics:
    """Summary of the batch processing run."""

    def __init__(
        self,
        discovered_files : int = 0,
        translated_files : int = 0,
        previewed_files : int = 0,
        skipped_files : int = 0,
        failed_files : int = 0,
    ):
        self.discovered_files = discovered_files
        self.translated_files = translated_files
        self.previewed_files = previewed_files
        self.skipped_files = skipped_files
        self.failed_files = failed_files

    def as_message(self) -> str:
        """Return a human readable summary string."""
        return (
            f"Processed {self.discovered_files} file(s): "
            f"{self.translated_files} translated, "
            f"{self.previewed_files} previewed, "
            f"{self.skipped_files} skipped, "
            f"{self.failed_files} failed"
        )


class ProgressDisplay:
    """Render incremental translation progress on a single console line."""

    def __init__(self, stream = None):
        self.stream = stream or sys.stdout
        self._current_file : pathlib.Path|None = None
        self._preview : bool = False
        self._total_batches : int = 0
        self._completed_batches : int = 0
        self._total_scenes : int = 0
        self._completed_scenes : int = 0
        self._total_lines : int = 0
        self._processed_lines : int = 0
        self._last_message_length : int = 0
        self._last_batch_label : str = ""
        self._last_batch_summary : str = ""
        self._last_scene_label : str = ""
        self._last_scene_summary : str = ""

    @contextmanager
    def track(self, translator : SubtitleTranslator, file_path : pathlib.Path, preview : bool):
        """Attach to translator events for the duration of one translation."""
        self._attach(translator, file_path, preview)
        try:
            yield
        finally:
            self._detach(translator)

    def _attach(self, translator : SubtitleTranslator, file_path : pathlib.Path, preview : bool) -> None:
        self._current_file = file_path
        self._preview = preview
        self._total_batches = 0
        self._completed_batches = 0
        self._total_scenes = 0
        self._completed_scenes = 0
        self._total_lines = 0
        self._processed_lines = 0
        self._last_message_length = 0
        self._last_batch_label = ""
        self._last_batch_summary = ""
        self._last_scene_label = ""
        self._last_scene_summary = ""
        translator.events.preprocessed.connect(self._on_preprocessed)
        translator.events.batch_translated.connect(self._on_batch_translated)
        translator.events.scene_translated.connect(self._on_scene_translated)

    def _detach(self, translator : SubtitleTranslator) -> None:
        translator.events.preprocessed.disconnect(self._on_preprocessed)
        translator.events.batch_translated.disconnect(self._on_batch_translated)
        translator.events.scene_translated.disconnect(self._on_scene_translated)

        self._render(final=True)
        self._current_file = None
        self._preview = False

    def _on_preprocessed(self, _sender, scenes : list) -> None:
        self._total_scenes = len(scenes)
        self._total_batches = sum(len(scene.batches) for scene in scenes)
        self._total_lines = sum(scene.linecount for scene in scenes)
        self._render()

    def _on_batch_translated(self, _sender, batch) -> None:
        self._completed_batches += 1
        self._processed_lines += batch.size
        self._last_batch_label = f"{batch.scene}.{batch.number}"
        self._last_batch_summary = batch.summary or ""
        logging.info("Translated batch %s: %s", self._last_batch_label, batch.summary or "no summary")
        self._render()

    def _on_scene_translated(self, _sender, scene) -> None:
        self._completed_scenes += 1
        self._last_scene_label = str(scene.number)
        self._last_scene_summary = scene.summary or ""
        logging.info("Completed scene %s: %s", self._last_scene_label, scene.summary or "no summary")
        self._render()

    def _render(self, final : bool = False) -> None:
        if not self._current_file:
            return
        scene_total = self._total_scenes if self._total_scenes else 0
        batch_total = self._total_batches if self._total_batches else 0
        parts = [
            f"Translating {self._current_file.name}",
            f"scenes {self._completed_scenes}/{scene_total}",
            f"batches {self._completed_batches}/{batch_total}",
        ]
        if self._total_lines:
            parts.append(f"lines {self._processed_lines}/{self._total_lines}")
        # if self._last_batch_summary:
        #     parts.append(f"last batch {self._last_batch_label}: {self._shorten(self._last_batch_summary)}")
        #if self._last_scene_summary:
        #    parts.append(f"scene {self._last_scene_label}: {self._shorten(self._last_scene_summary)}")
        if self._preview:
            parts.append("preview")
        message = " | ".join(parts)
        padding = ""
        if len(message) < self._last_message_length:
            padding = " " * (self._last_message_length - len(message))
        end = "\n" if final else "\r"
        self.stream.write(message + padding + end)
        self.stream.flush()
        self._last_message_length = len(message)

    def _shorten(self, text : str, limit : int = 60) -> str:
        summary = text.strip()
        if len(summary) <= limit:
            return summary
        return summary[:limit - 3] + "..."

def configure_logging(log_path : str, verbose : bool) -> None:
    """Configure logging to emit concise console output and detailed log file."""
    resolved_log_path = pathlib.Path(log_path).expanduser().resolve()
    resolved_log_path.parent.mkdir(parents=True, exist_ok=True)

    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)

    logging.root.setLevel(logging.DEBUG)

    # File handler captures everything
    file_handler = logging.FileHandler(resolved_log_path, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s'))
    logging.root.addHandler(file_handler)

    # Console handler only shows messages from this script, not PySubtrans internals
    console_handler = logging.StreamHandler(stream=sys.stderr)
    console_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    console_handler.setFormatter(logging.Formatter('%(message)s'))

    # Add a filter to only show messages from the batch script logger
    class BatchScriptFilter(logging.Filter):
        def filter(self, record):
            # Only show messages from __main__ (this script) and errors
            return record.name == '__main__' or record.levelno >= logging.ERROR

    console_handler.addFilter(BatchScriptFilter())
    logging.root.addHandler(console_handler)

def parse_args(argv : list[str]|None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Batch translate subtitles with PySubtrans")
    parser.add_argument("source", nargs="?", help="Directory containing subtitle files")
    parser.add_argument("destination", nargs="?", help="Directory to write translated subtitles")
    parser.add_argument("--provider", help="Translation provider name")
    parser.add_argument("--model", help="Model identifier for the provider")
    parser.add_argument("--apikey", dest="api_key", help="API key for the provider")
    parser.add_argument("--prompt", help="High level translation prompt")
    parser.add_argument("--language", dest="target_language", help="Target language for translation")
    parser.add_argument("--output-format", dest="output_format", help="Override the output subtitle format (e.g. srt)")
    parser.add_argument("--instructions", dest="instruction_file", help="Path to a file containing detailed instructions for the translator (system prompt)")
    parser.add_argument("--log-file", dest="log_file", help="Path to write the detailed log file")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose console logging")
    parser.add_argument("--preview", dest="preview", action="store_true", help="Enable preview mode")
    parser.add_argument("--option", action="append", default=[], metavar="KEY=VALUE",
                        help="Override additional Options settings (repeatable)")
    parser.set_defaults(preview=None)
    return parser.parse_args(argv)



def main(argv : list[str]|None = None) -> int:
    """Entry point for command line execution."""

    args = parse_args(argv)
    config = build_config(args)
    configure_logging(config.log_path, args.verbose)

    if not config.provider:
        logging.error("No translation provider specified.")
        return 1

    logging.info("Source directory: %s", str(config.source_path))
    logging.info("Destination directory: %s", str(config.destination_path))
    logging.info("Provider: %s", config.provider)
    if config.output_format:
        logging.info("Output format override: %s", config.output_format)

    logging.debug("Effective options: %s", redact_sensitive_values(config.options))

    logging.info(
        "Using provider '%s' model '%s' (preview=%s)",
        config.options.provider or 'unspecified',
        config.options.model or 'unspecified',
        config.options.get_bool('preview')
    )

    try:
        # Initialize the batch processor
        processor = BatchProcessor(config)

        try:
            # Run the batch processing workflow
            stats = processor.run()

        except SubtitleError as exc:
            logging.error("Batch processing failed: %s", exc)
            return 1
        except KeyboardInterrupt:
            logging.warning("Batch processing interrupted by user")
            return 130

        logging.info(stats.as_message())

    except Exception as error:
        message = error.message or str(error) if isinstance(error, SubtitleError) else str(error)
        logging.exception("An error occurred: %s", message)
        return 1

    return 0 if stats.failed_files == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
