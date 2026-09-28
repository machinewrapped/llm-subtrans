import argparse
import logging
import os
import signal
import sys
import cProfile
from pstats import Stats

_STARTUP_PROFILE_REQUESTED : bool = '--profile-startup' in sys.argv[1:]
_startup_profiler : cProfile.Profile|None = None

if _STARTUP_PROFILE_REQUESTED:
    _startup_profiler = cProfile.Profile()
    _startup_profiler.enable()

if not hasattr(sys, "_MEIPASS"):
    from check_imports import check_required_imports
    check_required_imports(['PySubtrans', 'GuiSubtrans', 'PySide6', 'scripts'], 'gui')

from PySubtrans.Helpers.ImportGuard import CaptureOriginalImport
from scripts.subtrans_common import InitLogger

# Must happen before PySide6 is imported; see PySubtrans.Helpers.ImportGuard.
CaptureOriginalImport()

# PySide6 6.9+ conflicts with debugpy's console handler on Windows during Qt init
if sys.platform == 'win32':
    _prev_sigint = signal.signal(signal.SIGINT, signal.SIG_IGN)

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtWidgets import QApplication

if sys.platform == 'win32':
    signal.signal(signal.SIGINT, _prev_sigint)
    del _prev_sigint
from PySubtrans.Helpers.Resources import ConfigureConfigDirFromArguments, GetConfigDir, GetSettingsPath
from PySubtrans.Options import Options
from PySubtrans.Helpers.Localization import initialize_localization, _
from GuiSubtrans.MainWindow import MainWindow

def parse_arguments():
    # Parse command line arguments
    ConfigureConfigDirFromArguments()
    parser = argparse.ArgumentParser(description='Translates subtitles using an AI service')
    parser.add_argument('filepath', nargs='?', help="Optional file to load on startup")
    parser.add_argument('-l', '--target-language', type=str, default=None, help="The target language for the translation")
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
    profile_group = parser.add_mutually_exclusive_group()
    profile_group.add_argument('--profile', action='store_true', help="Profile execution and write stats to the config directory")
    profile_group.add_argument('--profile-startup', action='store_true', help="Profile startup through the first window display")
    parser.add_argument('--preview', action='store_true', help="Run the translation pipeline without calling the translation provider (for testing)")
    parser.add_argument('--ratelimit', type=int, default=None, help="Maximum number of batches per minute to process")
    parser.add_argument('--scenethreshold', type=float, default=None, help="Number of seconds between lines to consider a new scene")
    parser.add_argument('--theme', type=str, default=None, help="Stylesheet to load")
    parser.add_argument('--portable', action='store_true', help="Store settings and logs in the .settings directory in the current directory")
    parser.add_argument('--configpath', type=str, default=None, help="Store settings and logs in the specified directory")

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
        'profile_startup': args.profile_startup,
        'preview': args.preview,
        'provider': args.provider,
        'rate_limit': args.ratelimit,
        'scene_threshold': args.scenethreshold,
        'target_language': args.target_language,
        'theme': args.theme
    }

    return arguments, args.filepath, logger_options

def write_profile(profiler : cProfile.Profile, filename : str, sort_key : str) -> None:
    """Write the first 100 profiling entries to the active config directory."""
    profile_path = os.path.join(GetConfigDir(), filename)
    with open(profile_path, 'w', encoding='utf-8') as stream:
        stats = Stats(profiler, stream=stream)
        stats.sort_stats(sort_key)
        stats.print_stats(100)

    logging.info(f"Profiling stats written to {profile_path}")

def finish_startup_profile(app : QApplication) -> None:
    """Write startup statistics after the first window paint and exit."""
    if _startup_profiler is not None:
        _startup_profiler.disable()
        write_profile(_startup_profiler, 'profile_guisubtrans_startup.txt', 'cumulative')

    app.quit()

class _StartupProfilePaintFilter(QObject):
    """Finish startup profiling after the first main-window paint."""

    def __init__(self, app : QApplication, parent : QObject):
        super().__init__(parent)
        self.app = app
        self._finish_scheduled = False

    def eventFilter(self, watched : QObject, event : QEvent) -> bool:
        if not self._finish_scheduled and event.type() == QEvent.Type.Paint:
            self._finish_scheduled = True
            QTimer.singleShot(0, lambda: finish_startup_profile(self.app))

        return False

def run_with_profiler(app):
    profiler = cProfile.Profile()
    profiler.enable()

    app.exec()

    profiler.disable()
    write_profile(profiler, 'profile_guisubtrans.txt', 'tottime')

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    # Force light mode because our themes were not built to be flexible
    app.styleHints().setColorScheme(Qt.ColorScheme.Light)

    arguments, filepath, logger_options = parse_arguments()

    # Load default options and update with any explicit arguments
    options = Options()

    if not arguments.get('firstrun'):
        if options.LoadSettings():
            logging.info(f"Loaded settings from {GetSettingsPath()}")

    options.update(arguments)

    # Initialize localization before creating GUI
    try:
        initialize_localization(options.ui_language)
    except Exception as e:
        logging.warning(f"Localization initialization failed: {e}")

    # Launch the GUI
    main_window = MainWindow( options=options, filepath=filepath)
    main_window.show()

    logging.info(_("Logging to {path}").format(path=logger_options.log_path))

    if arguments.get('profile_startup'):
        startup_profile_filter = _StartupProfilePaintFilter(app, main_window)
        main_window.installEventFilter(startup_profile_filter)
        app.exec()
    elif arguments.get('profile'):
        run_with_profiler(app)
    else:
        app.exec()
