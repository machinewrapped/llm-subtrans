"""Qt message filters for GUI tests.

Separate from tests.GuiTestSupport: this module needs PySide6 at its own top level, so it must only be imported after PySide6 has already been imported elsewhere (i.e. after tests.GuiTestSupport.ConfigureOffscreenPlatform() has had a chance to run).
"""
import sys

from PySide6.QtCore import QMessageLogContext, QtMsgType, qInstallMessageHandler


def InstallOffscreenSizeHintFilter() -> None:
    """Silence the offscreen platform plugin's harmless propagateSizeHints() notice.

    Showing a real widget under QT_QPA_PLATFORM=offscreen always logs this fixed message; it is not a categorized log message, so QT_LOGGING_RULES cannot filter it.
    Only this exact known-benign message is dropped here, so other genuine Qt warnings/errors raised during a test still surface normally.
    """
    def _filter(msg_type : QtMsgType, context : QMessageLogContext, message : str) -> None:
        if 'propagateSizeHints' in message:
            return
        print(message, file=sys.stderr)

    qInstallMessageHandler(_filter)
