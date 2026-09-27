import logging
import os
import unicodedata
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

def GetWrapKey(text : str, bucket_length : int = 10) -> tuple[int, ...]:
    """
    Group text by how it will wrap, for caching layout sizes.
    Each line wraps independently, so the key is the length of every line, rounded up to bucket_length.
    Sorted, because the order of the lines does not affect the total height.
    """
    if not text:
        return ()

    return tuple(sorted(-(-GetDisplayLength(line) // bucket_length) for line in text.split('\n')))

def GetDisplayLength(text : str) -> int:
    """
    Approximate width of text in Latin characters.
    East Asian wide and fullwidth characters take up about two.
    """
    if text.isascii():
        return len(text)

    return sum(2 if unicodedata.east_asian_width(char) in ('W', 'F') else 1 for char in text)

def WrapKeyDominates(key : tuple[int, ...], other : tuple[int, ...]) -> bool:
    """
    True if text with the first wrap key is at least as tall as text with the other at any width.
    That holds if it has at least as many lines, and its lines are at least as long when both are sorted longest first.
    """
    if len(key) < len(other):
        return False

    return all(length >= other_length for length, other_length in zip(reversed(key), reversed(other)))

def DescribeLineCount(line_count : int, translated_count : int) -> str:
    if translated_count == 0:
        return _("{count} lines").format(count=line_count)
    elif line_count == translated_count:
        return _("{count} lines translated").format(count=translated_count)
    else:
        return _("{done} of {total} lines translated").format(done=translated_count, total=line_count)

def ClearForm(layout : QFormLayout):
    """
    Clear the widgets from a layout.
    Widgets are hidden and unparented immediately, then deleted once the event loop runs, so a rebuild in the same cycle cannot leave stale widgets painted.
    """
    while layout.rowCount():
        result = layout.takeRow(0)  # Pylance: TakeRowResult missing attrs in stubs
        for attr in ("labelItem", "fieldItem"):
            item = getattr(result, attr, None)
            if item is None:
                continue
            widget = item.widget()
            if widget:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()