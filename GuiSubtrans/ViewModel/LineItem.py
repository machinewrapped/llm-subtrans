from GuiSubtrans.GuiHelpers import GetLineHeight
from PySubtrans.Helpers import UpdateFields
from PySubtrans.Helpers.Text import Linearise, emdash

from GuiSubtrans.ViewModel.ViewModelError import ViewModelError

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItem

blank_line = f"<font color='lightgrey'>{emdash}</font>"

class LineItem(QStandardItem):
    """
    Represents a single subtitle line in the viewmodel.
    This is used to display lines in the GUI and to update the model when changes are made.
    """
    def __init__(self, line_number : int, model : dict[str, str|int|float]):
        super().__init__(f"Line {line_number}")
        self.number : int = line_number
        self.line_model : dict[str, str|int|float] = model
        self.height = max(GetLineHeight(self.line_text), GetLineHeight(self.translation)) if self.translation else GetLineHeight(self.line_text)

        self._format_and_set_data()

    def Update(self, line_update : dict[str, str|int|float]) -> None:
        if not isinstance(line_update, dict):
            raise ViewModelError(f"Expected a dictionary, got a {type(line_update).__name__}")

        UpdateFields(self.line_model, line_update, ['start', 'end', 'text', 'translation'])

        number = line_update.get('number', None)
        if number is not None and not isinstance(number, int):
            raise ViewModelError(f"Line number must be an integer, got {type(number).__name__}")

        self.number = number or self.number

        self.height = max(GetLineHeight(self.line_text), GetLineHeight(self.translation)) if self.translation else GetLineHeight(self.line_text)

        self._format_and_set_data()

    def __str__(self) -> str:
        return f"{self.number}: {self.start} --> {self.end} | {Linearise(self.line_text)}"

    def __repr__(self) -> str:
        return f"{self.number}: {self.start} --> {self.end}"

    @property
    def start(self) -> str:
        if 'start' not in self.line_model:
            raise ViewModelError(f"Line model does not contain a valid 'start' field: {self.line_model}")

        start = self.line_model['start']
        if not isinstance(start, str):
            raise ViewModelError(f"Model field 'start' is not a string: {self.line_model}")

        return start

    @property
    def end(self) -> str:
        if 'end' not in self.line_model:
            raise ViewModelError(f"Line model does not contain a valid 'end' field: {self.line_model}")

        end = self.line_model['end']

        if not isinstance(end, str):
            raise ViewModelError(f"Model field 'end' is not a string: {self.line_model}")

        return end

    @property
    def duration(self) -> str:
        if 'duration' not in self.line_model:
            raise ViewModelError(f"Line model does not contain a valid 'duration' field: {self.line_model}")

        duration = self.line_model['duration']
        if not isinstance(duration, str):
            raise ViewModelError(f"Model field 'duration' is not a string: {self.line_model}")

        return duration

    @property
    def gap(self) -> str:
        if 'gap' not in self.line_model:
            return ""

        gap = self.line_model['gap']
        if not isinstance(gap, str):
            raise ViewModelError(f"Model field 'gap' is not a string: {self.line_model}")

        return gap

    @property
    def style(self) -> str|None:
        if 'style' not in self.line_model:
            return None

        style = self.line_model['style']
        if style is not None and not isinstance(style, str):
            raise ViewModelError(f"Model field 'style' is not a string: {self.line_model}")

        return style

    @property
    def line_text(self) -> str:
        if 'text' not in self.line_model:
            raise ViewModelError(f"Line model does not contain a valid 'text' field: {self.line_model}")

        text = self.line_model['text']
        if not isinstance(text, str):
            raise ViewModelError(f"Model field 'text' is not a string: {self.line_model}")
        
        return text

    @property
    def formatted_text(self) -> str:
        text = self.line_model.get('formatted_text', self.line_model.get('text', ''))
        if not isinstance(text, str):
            raise ViewModelError(f"Model field 'text' is not a string: {self.line_model}")
        
        return text

    @property
    def translation(self) -> str|None:
        translation = self.line_model.get('translation', None)
        if translation is None or not isinstance(translation, str):
            return None
        return translation

    @property
    def translation_text(self) -> str:
        translation = self.line_model.get('formatted_translation', self.line_model.get('translation'))
        if translation is None or not isinstance(translation, str):
            return blank_line
        return translation

    @property
    def scene(self) -> int:
        if 'scene' not in self.line_model:
            raise ViewModelError(f"Line model does not contain a valid 'scene' field: {self.line_model}")

        scene = self.line_model['scene']
        if not isinstance(scene, int):
            raise ViewModelError(f"Model field 'scene' is not an integer: {self.line_model}")

        return scene

    @property
    def batch(self) -> int:
        if 'batch' not in self.line_model:
            raise ViewModelError(f"Line model does not contain a valid 'batch' field: {self.line_model}")

        batch = self.line_model['batch']
        if not isinstance(batch, int):
            raise ViewModelError(f"Model field 'batch' is not an integer: {self.line_model}")

        return batch

    def _format_and_set_data(self) -> None:
        """
        Format text for GUI display and set the data on the model.
        """
        if 'text' in self.line_model and isinstance(self.line_model['text'], str):
            self.line_model['formatted_text'] = self._format_text_for_display(self.line_model['text'])
        else:
            self.line_model['formatted_text'] = blank_line

        if 'translation' in self.line_model and isinstance(self.line_model['translation'], str):
            self.line_model['formatted_translation'] = self._format_text_for_display(self.line_model['translation'])
        else:
            self.line_model['formatted_translation'] = blank_line

        self.setData(self.line_model, Qt.ItemDataRole.UserRole)

    def _format_text_for_display(self, text : str) -> str:
        """
        Format text for GUI display by converting soft line breaks to spaces.
        """
        if not text:
            return text
        return text.replace('<wbr>', ' ')