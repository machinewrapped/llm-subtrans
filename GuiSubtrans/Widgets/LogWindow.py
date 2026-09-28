import logging

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QTextCursor, QTextCharFormat, QColor
from PySide6.QtWidgets import QTextEdit

class LogWindow(QTextEdit):
    enqueue = Signal(str, str)

    LEVEL_COLORS = {
        "DEBUG":   QColor(135, 206, 250),
        "INFO":    QColor(255, 255, 255),
        "WARNING": QColor(255, 255,   0),
        "ERROR":   QColor(255,   0,   0),
        "CRITICAL":QColor(255,   0,   255)
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)

        self.enqueue.connect(self._append, Qt.ConnectionType.QueuedConnection)

        handler = QtLogHandler(self)
        handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(message)s', datefmt='%A, %H:%M:%S'))
        logging.getLogger().addHandler(handler)

    @Slot(str, str)
    def _append(self, msg: str, level: str):
        try:
            scrollbar = self.verticalScrollBar()
            autoscroll = scrollbar.value() == scrollbar.maximum() or self.textCursor().atEnd()

            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)

            text_format = QTextCharFormat()
            text_format.setForeground(self.LEVEL_COLORS.get(level, QColor(0, 0, 0)))
            cursor.insertText(msg + '\n', text_format)

            if autoscroll:
                    scrollbar.setValue(scrollbar.maximum())
        except:
            pass

class QtLogHandler(logging.Handler):
    def __init__(self, log_window : LogWindow):
        super().__init__(logging.INFO)
        self._log_window = log_window

    def emit(self, record):
        try:
            msg = self.format(record)
            self._log_window.enqueue.emit(msg, record.levelname)
        except Exception:
            self.handleError(record)

