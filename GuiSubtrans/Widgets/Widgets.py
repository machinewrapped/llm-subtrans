from PySide6.QtCore import Signal
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QFrame,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QTextEdit,
    QGridLayout,
    QSizePolicy
)
from GuiSubtrans.ViewModel.LineItem import LineItem
from PySubtrans.Helpers.Localization import _

class TreeViewItemWidget(QFrame):
    def __init__(self, content, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        properties = content.get('properties', {})

        layout = QVBoxLayout()
        layout.setSpacing(0)
        layout.setContentsMargins(4, 4, 8, 8)

        if content.get('heading'):
            header_widget = WidgetHeader(content['heading'], parent=self)
            self._set_properties(header_widget, properties)
            layout.addWidget(header_widget)

        if content.get('subheading'):
            subheading_widget = WidgetSubheading(content['subheading'], parent=self)
            self._set_properties(subheading_widget, properties)
            layout.addWidget(subheading_widget)

        if content.get('body'):
            body_widget = WidgetBody(content['body'], parent=self)
            self._set_properties(body_widget, properties)
            layout.addWidget(body_widget)
        
        if content.get('footer'):
            footer_widget = WidgetFooter(content['footer'], parent=self)
            self._set_properties(footer_widget, properties)
            layout.addWidget(footer_widget)

        self._set_properties(self, properties)
        self.setLayout(layout)

    def _set_properties(self, widget : QWidget, properties : dict):
        for key, value in properties.items():
            widget.setProperty(key, value)


class WidgetHeader(QLabel):
    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

class WidgetSubheading(QLabel):
    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

class WidgetFooter(QFrame):
    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        padding = QLabel("")
        padding.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(padding)

        textlabel = QLabel(text)
        textlabel.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout.addWidget(textlabel)

        self.setLayout(layout)

class WidgetBody(QLabel):
    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setWordWrap(True)

class LineItemView(QWidget):

    def __init__(self, line : LineItem, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout()
        layout.setSpacing(2)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(LineItemHeader(line, parent=self))
        h_layout = QHBoxLayout()
        h_layout.addWidget(LineItemBody(line.formatted_text, parent=self))
        h_layout.addWidget(LineItemBody(line.translation_text or "", parent=self))
        layout.addLayout(h_layout)

        self.setLayout(layout)

class LineItemHeader(QFrame):
    def __init__(self, line : LineItem, parent=None):
        super().__init__(parent)
        
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        leftLabel = QLabel(FormatLineHeader(line))
        leftLabel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        leftLabel.setObjectName("line-header-left")

        rightLabel = QLabel(FormatLineMeta(line))
        rightLabel.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        rightLabel.setObjectName("line-header-right")

        layout.addWidget(leftLabel)
        layout.addWidget(rightLabel)
        self.setLayout(layout)

class LineItemBody(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setWordWrap(True)

def FormatLineHeader(line : LineItem) -> str:
    """
    Header text for a subtitle row (line number and timecodes).
    Pure function so the format is unit-testable without a display.
    """
    return f"[{str(line.number)}] {str(line.start)} --> {str(line.end)}"

def FormatLineMeta(line : LineItem) -> str:
    """
    Right-hand header text: gap/length plus style and speaker annotations.
    Pure function so the format is unit-testable without a display.
    """
    if line.gap:
        meta = _("Gap: {gap}, Length: {duration}").format(gap=str(line.gap), duration=str(line.duration))
    else:
        meta = _("Length: {duration}").format(duration=str(line.duration))
    if line.style:
        meta += f", Style: {line.style}"
    if line.speaker:
        meta += _(", Speaker: {speaker}").format(speaker=line.speaker)
    return meta

class OptionsGrid(QGridLayout):
    """
    Grid layout for options (styling class)
    """
    def __init__(self, parent = None) -> None:
        super().__init__(parent)

class TextBoxEditor(QTextEdit):
    """
    Multi-line editor that provides a signal when text contents change
    """
    editingFinished = Signal(str)

    _original = None

    def focusInEvent(self, e) -> None:
        self._original = self.toPlainText()
        return super().focusInEvent(e)

    def focusOutEvent(self, e) -> None:
        text = self.toPlainText()
        if text != self._original:
            self.editingFinished.emit(text)
        return super().focusOutEvent(e)
    
    def SetText(self, text):
        self.setText(text)
        self.setPlainText(text)

