import argparse
import logging
import os
import sys
import cProfile
from pstats import Stats

if not hasattr(sys, "_MEIPASS"):
    from check_imports import check_required_imports
    check_required_imports(['PySubtrans', 'GuiSubtrans', 'PySide6', 'scripts'], 'gui')

from scripts.subtrans_common import InitLogger
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PySubtrans.Options import Options, settings_path, config_dir
from PySubtrans.Helpers.Localization import initialize_localization, _
from GuiSubtrans.MainWindow import MainWindow

def parse_arguments():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Translates subtitles using an AI service')
    parser.add_argument('filepath', nargs='?', help="Optional file to load on startup")
    parser.add_argument('-l', '--target_language', type=str, default=None, help="The target language for the translation")
    parser.add_argument('-p', '--provider', type=str, default=None, help="The translation provider to use")
    parser.add_argument('-m', '--model', type=str, default=None, help="The model to use for translation")
    parser.add_argument('--batchthreshold', type=float, default=None, help="Number of seconds between lines to consider for batching")
    parser.add_argument('--debug', action='store_true', help="Run with DEBUG log level")
    parser.add_argument('--firstrun', action='store_true', help="Show the first-run options dialog on launch")
    parser.add_argument('--includeoriginal', action='store_true', help="Include the original text in the translated subtitles")
    parser.add_argument('--maxbatchsize', type=int, default=None, help="Maximum number of lines before starting a new batch is compulsory")
    parser.add_argument('--maxlines', type=int, default=None, help="Maximum number of batches to process")
    parser.add_argument('--minbatchsize', type=int, default=None, help="Minimum number of lines to consider starting a new batch")
    parser.add_argument('--postprocess', action='store_true', default=None, help="Postprocess the subtitles after translation")
    parser.add_argument('--preprocess', action='store_true', default=None, help="Preprocess the subtitles before translation")
    parser.add_argument('--profile', action='store_true', help="Profile execution and write stats to the console")
    parser.add_argument('--project', type=str, default="true", help="How to process the project file (read, write, preview, reload, reparse, retranslate)")
    parser.add_argument('--ratelimit', type=int, default=None, help="Maximum number of batches per minute to process")
    parser.add_argument('--scenethreshold', type=float, default=None, help="Number of seconds between lines to consider a new scene")
    parser.add_argument('--theme', type=str, default=None, help="Stylesheet to load")

    try:
        args = parser.parse_args()
    except SystemExit as e:
        print(f"Argument error: {e}")
        raise

    logger_options = InitLogger("gui-subtrans", args.debug)

    arguments = {
        'firstrun': args.firstrun,
        'include_original': args.includeoriginal,
        'max_batch_size': args.maxbatchsize,
        'max_lines': args.maxlines,
        'min_batch_size': args.minbatchsize,
        'model': args.model,
        'postprocess_translation': args.postprocess,
        'preprocess_subtitles': args.preprocess,
        'profile': args.profile,
        'provider': args.provider,
        'rate_limit': args.ratelimit,
        'scene_threshold': args.scenethreshold,
        'target_language': args.target_language,
        'theme': args.theme
    }

    return arguments, args.filepath, logger_options

def run_with_profiler(app):
    profiler = cProfile.Profile()
    profiler.enable()

    app.exec()

    profiler.disable()

    profile_path = os.path.join(config_dir, 'profile_guisubtrans.txt')
    with open(profile_path, 'w') as stream:
        stats = Stats(profiler, stream=stream)
        stats.sort_stats('tottime')
        stats.print_stats(100)

    logging.info(f"Profiling stats written to {profile_path}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    # Force light mode because our themes were not built to be flexible
    app.styleHints().setColorScheme(Qt.ColorScheme.Light)

    arguments, filepath, logger_options = parse_arguments()

    # Load default options and update with any explicit arguments
    options = Options()

    if not arguments.get('firstrun'):
        options.MigrateSettings()
        if options.LoadSettings():
            logging.info(f"Loaded settings from {settings_path}")

    options.update(arguments)
    options.InitialiseInstructions()

    # Initialize localization before creating GUI
    try:
        initialize_localization(options.ui_language)
    except Exception as e:
        logging.warning(f"Localization initialization failed: {e}")

    # Launch the GUI
    main_window = MainWindow( options=options, filepath=filepath)
    main_window.show()

    logging.info(_("Logging to {path}").format(path=logger_options.log_path))

    if arguments.get('profile'):
        run_with_profiler(app)
    else:
        app.exec()
