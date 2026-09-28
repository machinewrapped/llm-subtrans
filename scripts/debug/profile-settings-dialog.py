"""Profile the Settings dialog from toolbar click to first paint.

Run with the project virtualenv:

    ./envsubtrans/Scripts/python.exe scripts/debug/profile-settings-dialog.py

Wait until the log reports that the Settings button is enabled, then click it.
Profiling starts when the click reaches ShowSettingsDialog and stops the moment
the dialog receives its first paint. Stats are written to
profile_settings_dialog.txt in the application config directory (the same
location profile-startup writes to).
"""
import cProfile
import logging
import os
import sys
from pstats import Stats

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

if not hasattr(sys, "_MEIPASS"):
    from scripts.check_imports import check_required_imports
    check_required_imports(['PySubtrans', 'GuiSubtrans', 'PySide6', 'scripts'], 'gui')

from PySubtrans.Helpers.ImportGuard import CaptureOriginalImport
from scripts.subtrans_common import InitLogger

# Must happen before PySide6 is imported; see PySubtrans.Helpers.ImportGuard.
CaptureOriginalImport()

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtWidgets import QApplication, QWidget

from PySubtrans.Helpers.Resources import ConfigureConfigDirFromArguments, GetConfigDir
from PySubtrans.Helpers.Localization import initialize_localization
from PySubtrans.Options import Options
from GuiSubtrans.GuiInterface import GuiInterface
from GuiSubtrans.MainWindow import MainWindow
from GuiSubtrans.SettingsDialog import SettingsDialog

PROFILE_FILENAME = 'profile_settings_dialog.txt'

_state = {
    'profiler': None,
    'filter': None,
    'written': False,
}


class _FirstPaintFilter(QObject):
    """Stop the profiler and write stats at the dialog's first paint."""

    def eventFilter(self, watched : QObject, event : QEvent) -> bool:
        if (not _state['written'] and event.type() == QEvent.Type.Paint
                and isinstance(watched, QWidget)
                and isinstance(watched.window(), SettingsDialog) and watched.isVisible()):
            _state['written'] = True
            profiler = _state['profiler']
            if isinstance(profiler, cProfile.Profile):
                profiler.disable()
                _write_profile(profiler)
        return False


def _write_profile(profiler : cProfile.Profile) -> None:
    """Write cumulative and total-time stats to the config directory."""
    profile_path = os.path.join(GetConfigDir(), PROFILE_FILENAME)
    with open(profile_path, 'w', encoding='utf-8') as stream:
        stream.write("Settings dialog profile: toolbar click -> first paint\n\n")
        stream.write("=== ordered by cumulative ===\n")
        stats = Stats(profiler, stream=stream)
        stats.sort_stats('cumulative')
        stats.print_stats(120)

        stream.write("\n=== ordered by internal (tottime) ===\n")
        stats.sort_stats('tottime')
        stats.print_stats(60)

    logging.info(f"Settings dialog profile written to {profile_path}")


_original_show_settings = GuiInterface.ShowSettingsDialog


def _profiled_show_settings(self : GuiInterface) -> None:
    """Profile a single Settings dialog lifetime from slot entry to first paint."""
    profiler = cProfile.Profile()
    paint_filter = _FirstPaintFilter()
    _state['profiler'] = profiler
    _state['filter'] = paint_filter
    _state['written'] = False

    app = QApplication.instance()
    if app is not None:
        app.installEventFilter(paint_filter)

    profiler.enable()
    try:
        _original_show_settings(self)
    finally:
        profiler.disable()
        if app is not None:
            app.removeEventFilter(paint_filter)


def _report_settings_enabled(main_window : MainWindow) -> None:
    """Log once the toolbar Settings action is clickable after warm-up."""
    gui = main_window.gui_interface
    action = main_window.toolbar.GetAction('Settings')
    if action.isEnabled() and gui._provider_warmup_started:
        logging.info("Settings button is enabled - click it now to profile the dialog")
        return

    QTimer.singleShot(250, lambda: _report_settings_enabled(main_window))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.styleHints().setColorScheme(Qt.ColorScheme.Light)

    ConfigureConfigDirFromArguments()
    logger_options = InitLogger("profile-settings", True)
    logging.info(f"Profiling log: {logger_options.log_path}")

    options = Options()
    if options.LoadSettings():
        logging.info("Loaded settings")

    initialize_localization(options.ui_language)

    GuiInterface.ShowSettingsDialog = _profiled_show_settings

    main_window = MainWindow(options=options, filepath=None)
    main_window.show()

    logging.info("Waiting for startup and provider warm-up before the Settings button is enabled")
    QTimer.singleShot(250, lambda: _report_settings_enabled(main_window))

    app.exec()
