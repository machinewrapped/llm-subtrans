"""Shared bootstrap for tests that create a real Qt application.

Kept separate from tests.Helpers, which is also imported by non-GUI test modules and must not carry a hard PySide6 dependency.
Also kept separate from tests.GuiTestMessageFilters (which does need PySide6 at its own top level): ConfigureOffscreenPlatform() must run before the first PySide6 import anywhere, including a top-level import in this module itself.
"""
import os
import sys


def ConfigureOffscreenPlatform() -> None:
    """Set the Qt platform and logging environment before PySide6 is imported.

    Must run before the first PySide6 import: QT_QPA_PLATFORM only takes effect at QApplication construction and QT_LOGGING_RULES at Qt's logging setup, both of which happen as a side effect of importing PySide6.
    """
    if sys.platform != 'win32':
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    os.environ.setdefault('QT_LOGGING_RULES', 'qt.qpa.fonts=false')
