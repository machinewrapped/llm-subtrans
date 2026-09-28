from collections.abc import Callable
from enum import Enum
import json
from datetime import datetime
from typing import Any, cast

from PySide6.QtCore import Qt, Signal, QSignalBlocker
from PySide6.QtWidgets import (QWidget, QLabel, QLineEdit, QPushButton, QSpinBox, QDoubleSpinBox, QComboBox, QCheckBox, QTextEdit, QSizePolicy, QHBoxLayout, QVBoxLayout)
from PySide6.QtGui import QTextOption

from PySubtrans.Helpers import GetValueFromName, GetValueName
from PySubtrans.Helpers.Localization import LocaleDisplayItem, _
from PySubtrans.Options import INFO_OPTION, MULTILINE_OPTION

class OptionWidget(QWidget):
    contentChanged = Signal()

    def __init__(self, key, initial_value, parent=None, tooltip = None):
        super().__init__(parent)
        self.key = key
        self.name = _(key)
        self.initial_value = initial_value
        if tooltip:
            self.setToolTip(tooltip)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def GetValue(self):
        raise NotImplementedError

    def SetValue(self, value : Any):
        raise NotImplementedError


def ParseOptionDefinition(option_definition : Any) -> tuple[Any, str|None, str|None]:
    """Return the value type, tooltip, and placeholder metadata for an option."""
    if not isinstance(option_definition, tuple):
        return option_definition, None, None

    value_type = option_definition[0]
    tooltip = option_definition[1] if len(option_definition) > 1 else None
    placeholder = option_definition[2] if len(option_definition) > 2 else None
    return value_type, tooltip, placeholder


class TextOptionWidget(OptionWidget):
    def __init__(self, key, initial_value, tooltip = None, placeholder = None):
        super().__init__(key, initial_value, tooltip=tooltip)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0,0,0,0)
        self.text_field = QLineEdit(self)
        self.text_field.setText(initial_value)
        if placeholder is not None:
            self.SetPlaceholderText(placeholder)
        self.text_field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        # self.text_field.textChanged.connect(self.contentChanged)
        self.text_field.editingFinished.connect(self.contentChanged)
        self._layout.addWidget(self.text_field)

    def GetValue(self):
        return self.text_field.text()

    def SetValue(self, value : Any):
        if not isinstance(value, str):
            value = str(value)
        self.text_field.setText(value)

    def SetPlaceholderText(self, text : str) -> None:
        """Set guidance shown while the text field is empty."""
        self.text_field.setPlaceholderText(text)

    def SetEnabled(self, enabled : bool):
        self.text_field.setEnabled(enabled)

    def SetVisible(self, is_visible : bool):
        self.text_field.setVisible(is_visible)

class MultilineTextOptionWidget(OptionWidget):
    def __init__(self, key, initial_value, tooltip = None):
        super().__init__(key, initial_value, tooltip=tooltip)
        content = self._get_content(initial_value).strip()

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self.text_field = QTextEdit(self)
        self.text_field.setAcceptRichText(False)
        self.text_field.setPlainText(content)
        self.text_field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
        self.text_field.textChanged.connect(self.contentChanged)
        self.text_field.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self._layout.addWidget(self.text_field)

    def GetValue(self):
        return self.text_field.toPlainText()

    def SetValue(self, value : Any):
        if not isinstance(value, str):
            value = str(value)

        self.text_field.setPlainText(value)

    def SetReadOnly(self, is_read_only : bool):
        self.text_field.setReadOnly(is_read_only)

    def SetEnabled(self, enabled : bool):
        self.text_field.setEnabled(enabled)

    def SetVisible(self, is_visible : bool):
        self.text_field.setVisible(is_visible)

    def _get_content(self, value):
        """
        Convert a value to a human-readable string
        """
        if isinstance(value, str):
            return value.replace('\\n', '\n')
        elif isinstance(value, list):
            return '\n'.join(self._get_content(x) for x in value)
        elif isinstance(value, dict):
            jsonstring = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=self._encode_content)
            return self._get_content(jsonstring)
        elif isinstance(value, (int, float)):
            return f'{value:,}'  # Format number with commas
        elif isinstance(value, datetime):
            return value.strftime('%Y-%m-%d %H:%M:%S')  # Format date
        elif value is None:
            return ''  # Return empty string for None
        else:
            return str(value)

    def _encode_content(self, obj):
        return str(obj)

class InformationOptionWidget(OptionWidget):
    """Read-only rich text block describing a setting or provider.

    The content is rendered as a word-wrapped label that grows with the text,
    so it never claims the remaining space of the form the way a text editor does.
    """

    def __init__(self, key, initial_value, tooltip = None):
        super().__init__(key, initial_value, tooltip=tooltip)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

        self.info_label = QLabel(self)
        self.info_label.setWordWrap(True)
        self.info_label.setTextFormat(Qt.TextFormat.RichText)
        self.info_label.setOpenExternalLinks(True)
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.info_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.info_label.setMinimumWidth(400)
        self.SetValue(initial_value)

        self._layout.addWidget(self.info_label)

    def GetValue(self):
        return self.info_label.text()

    def SetValue(self, value : Any):
        if not isinstance(value, str):
            value = str(value)

        self.info_label.setText(value)

    def SetEnabled(self, enabled : bool):
        self.info_label.setEnabled(enabled)

    def SetVisible(self, is_visible : bool):
        self.info_label.setVisible(is_visible)

class IntegerOptionWidget(OptionWidget):
    def __init__(self, key, initial_value, tooltip = None):
        super().__init__(key, initial_value, tooltip=tooltip)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self.spin_box = QSpinBox(self)
        self.spin_box.setMaximum(99999)
        self.spin_box.setMinimumWidth(100)
        self.spin_box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.spin_box.valueChanged.connect(self.contentChanged)
        if initial_value:
            self.spin_box.setValue(initial_value)
        self._layout.addWidget(self.spin_box)

    def GetValue(self):
        return self.spin_box.value()

    def SetValue(self, value : int):
        self.spin_box.setValue(value)

    def SetRange(self, min : int, max : int):
        self.spin_box.setRange(min, max)

    def SetEnabled(self, enabled : bool):
        self.spin_box.setEnabled(enabled)

    def SetVisible(self, is_visible : bool):
        self.spin_box.setVisible(is_visible)

class FloatOptionWidget(OptionWidget):
    def __init__(self, key, initial_value, tooltip = None):
        super().__init__(key, initial_value, tooltip=tooltip)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self.double_spin_box = QDoubleSpinBox(self)
        self.double_spin_box.setMaximum(9999.99)
        self.double_spin_box.setMinimumWidth(100)
        self.double_spin_box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.double_spin_box.valueChanged.connect(self.contentChanged)
        if initial_value:
            self.double_spin_box.setValue(initial_value)
        self._layout.addWidget(self.double_spin_box)

    def GetValue(self):
        return self.double_spin_box.value()

    def SetValue(self, value : float):
        self.double_spin_box.setValue(value)

    def SetRange(self, min : float, max : float):
        self.double_spin_box.setRange(min, max)

    def SetSuffix(self, suffix : str):
        self.double_spin_box.setSuffix(suffix)

    def SetEnabled(self, enabled : bool):
        self.double_spin_box.setEnabled(enabled)

    def SetVisible(self, is_visible : bool):
        self.double_spin_box.setVisible(is_visible)

class CheckboxOptionWidget(OptionWidget):
    def __init__(self, key, initial_value, tooltip = None):
        super().__init__(key, initial_value, tooltip=tooltip)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self.check_box = QCheckBox(self)
        self.check_box.stateChanged.connect(self.contentChanged)
        if initial_value:
            self.check_box.setChecked(initial_value)
        self._layout.addWidget(self.check_box)

    def GetValue(self):
        return self.check_box.isChecked()

    def SetValue(self, value : Any):
        if not isinstance(value, bool):
            raise ValueError(f"Invalid value type: {type(value)}. Expected bool.")

        self.check_box.setChecked(value)

    def SetEnabled(self, enabled : bool):
        self.check_box.setEnabled(enabled)

    def SetVisible(self, is_visible : bool):
        self.check_box.setVisible(is_visible)

class DropdownOptionWidget(OptionWidget):
    def __init__(self, key, values, initial_value, tooltip = None):
        super().__init__(key, initial_value, tooltip=tooltip)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self.combo_box = QComboBox(self)
        self.combo_box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.SetOptions(values, initial_value)
        self.combo_box.currentTextChanged.connect(self.contentChanged)
        self._layout.addWidget(self.combo_box)

    def GetValue(self):
        value = self.combo_box.currentText()
        if value and self.values:
            return GetValueFromName(value, self.values)
        return None

    def SetValue(self, value : Any):
        if not isinstance(value, (str, Enum, LocaleDisplayItem)):
            raise ValueError(f"Invalid value type: {type(value)}. Expected str, Enum, or LocaleDisplayItem.")

        self.combo_box.setCurrentIndex(self.combo_box.findText(str(value)))

    def SetOptions(self, values, selected_value = None):
        with QSignalBlocker(self.combo_box):
            self.combo_box.clear()
            self.values = values
            selected_value_name = GetValueName(selected_value) if selected_value else None
            for value in values:
                value_name = GetValueName(value)
                self.combo_box.addItem(value_name)
                if selected_value and value_name == selected_value_name:
                    self.combo_box.setCurrentIndex(self.combo_box.count() - 1)
                elif isinstance(value, LocaleDisplayItem) and selected_value == value.code:
                    self.combo_box.setCurrentIndex(self.combo_box.count() - 1)

            self.combo_box.setEnabled(len(values) > 1)

    def SetEnabled(self, enabled : bool):
        self.combo_box.setEnabled(enabled)

    def SetVisible(self, is_visible : bool):
        self.combo_box.setVisible(is_visible)

class ButtonOptionWidget(OptionWidget):
    """A single action button. The action callable receives the current value
    and returns a new value (or ``None`` to cancel)."""

    def __init__(self, key, initial_value, button_label : str, action : Callable[[str], str|None], tooltip=None):
        super().__init__(key, initial_value, tooltip=tooltip)
        self._action = action
        self._value = initial_value or ''

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

        self._button = QPushButton(button_label, self)
        self._button.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._button.clicked.connect(self._on_button_clicked)
        self._layout.addWidget(self._button)

    def _on_button_clicked(self) -> None:
        result = self._action(self._value)
        if result is not None:
            self._value = result
            self.contentChanged.emit()

    def GetValue(self):
        return self._value

    def SetValue(self, value : Any):
        self._value = str(value) if value else ''

    def SetEnabled(self, enabled : bool):
        self._button.setEnabled(enabled)

    def SetVisible(self, is_visible : bool):
        self._button.setVisible(is_visible)


class ButtonTextOptionWidget(OptionWidget):
    """Text field with an action button. The action callable receives the
    current text and returns a new value (or ``None`` to cancel)."""

    def __init__(self, key, initial_value, button_label : str, action : Callable[[str], str|None], tooltip=None):
        super().__init__(key, initial_value, tooltip=tooltip)
        self._action = action

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

        self.text_field = QLineEdit(self)
        self.text_field.setText(initial_value or '')
        self.text_field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.text_field.editingFinished.connect(self.contentChanged)
        self._layout.addWidget(self.text_field)

        self._button = QPushButton(button_label, self)
        self._button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._button.clicked.connect(self._on_button_clicked)
        self._layout.addWidget(self._button)

    def _on_button_clicked(self) -> None:
        result = self._action(self.text_field.text())
        if result is not None:
            self.text_field.setText(result)
            self.contentChanged.emit()

    def GetValue(self):
        return self.text_field.text()

    def SetValue(self, value : Any):
        if not isinstance(value, str):
            value = str(value)
        self.text_field.setText(value)

    def SetEnabled(self, enabled : bool):
        self.text_field.setEnabled(enabled)
        self._button.setEnabled(enabled)

    def SetVisible(self, is_visible : bool):
        self.text_field.setVisible(is_visible)
        self._button.setVisible(is_visible)


def CreateOptionWidget(key, initial_value, key_type, tooltip = None, placeholder = None) -> OptionWidget:
    """Create an option widget from a type or option definition."""
    key_type, definition_tooltip, definition_placeholder = ParseOptionDefinition(key_type)
    tooltip = tooltip if tooltip is not None else definition_tooltip
    placeholder = placeholder if placeholder is not None else definition_placeholder

    if isinstance(key_type, list):
        return DropdownOptionWidget(key, key_type, initial_value, tooltip=tooltip)
    elif isinstance(key_type, type) and issubclass(key_type, Enum):
        return DropdownOptionWidget(key, key_type, initial_value, tooltip=tooltip)
    elif key_type == MULTILINE_OPTION:
        return MultilineTextOptionWidget(key, initial_value, tooltip=tooltip)
    elif key_type == INFO_OPTION:
        return InformationOptionWidget(key, initial_value, tooltip=tooltip)
    elif key_type == str:
        return TextOptionWidget(key, initial_value, tooltip=tooltip, placeholder=placeholder)
    elif key_type == int:
        return IntegerOptionWidget(key, initial_value, tooltip=tooltip)
    elif key_type == float:
        return FloatOptionWidget(key, initial_value, tooltip=tooltip)
    elif key_type == bool:
        return CheckboxOptionWidget(key, initial_value, tooltip=tooltip)
    elif callable(key_type):
        action = cast(Callable[[str], str|None], key_type)
        if initial_value:
            return ButtonTextOptionWidget(key, initial_value, placeholder or '', action, tooltip=tooltip)
        return ButtonOptionWidget(key, initial_value, placeholder or '', action, tooltip=tooltip)
    else:
        raise ValueError('Unsupported option type: ' + str(type(initial_value)))
