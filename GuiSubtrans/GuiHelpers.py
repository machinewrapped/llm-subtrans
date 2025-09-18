import logging
import os
import darkdetect # type: ignore

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QFormLayout)

from PySubtrans.Helpers.Resources import GetResourcePath
from PySubtrans.Helpers.Localization import _

def GetThemeNames():
    themes = []
    theme_path = GetResourcePath("theme")
    for file in os.listdir(theme_path):
        if file.endswith(".qss"):
            theme_name = os.path.splitext(file)[0]
            themes.append(theme_name)

    themes.sort()
    return themes

def LoadStylesheet(name):
    if not name or name == "default":
        name = "subtrans-dark" if darkdetect.isDark() else "subtrans"

    filepath = GetResourcePath("theme", f"{name}.qss")
    logging.info(f"Loading stylesheet from {filepath}")
    with open(filepath, 'r') as file:
        stylesheet = file.read()

    app : QApplication|None = QApplication.instance() # type: ignore
    if app is not None:
        app.setStyleSheet(stylesheet)

        scheme : Qt.ColorScheme = Qt.ColorScheme.Dark if 'dark' in name else Qt.ColorScheme.Light
        app.styleHints().setColorScheme(scheme)

    return stylesheet

def GetLineHeight(text: str, wrap_length: int = 60) -> int:
    """
    Calculate the number of lines for a given text with wrapping and newline characters.

    :param text: The input text.
    :param wrap_length: The maximum number of characters per line.
    :return: The total number of lines.
    """
    if not text:
        return 0

    wraps = -(-len(text) // wrap_length) if wrap_length else 0  # Ceiling division
    return text.count('\n') + wraps

def DescribeLineCount(line_count : int, translated_count : int) -> str:
    if translated_count == 0:
        return _("{count} lines").format(count=line_count)
    elif line_count == translated_count:
        return _("{count} lines translated").format(count=translated_count)
    else:
        return _("{done} of {total} lines translated").format(done=translated_count, total=line_count)

def ClearForm(layout : QFormLayout):
    """
    Clear the widgets from a layout
    """
    while layout.rowCount():
        result = layout.takeRow(0)  # Pylance: TakeRowResult missing attrs in stubs
        for attr in ("labelItem", "fieldItem"):
            item = getattr(result, attr, None)
            if item is None:
                continue
            widget = item.widget()
            if widget:
                widget.deleteLater()