import logging
from typing import Any

from PySide6.QtCore import Qt

from GUI.GuiHelpers import DescribeLineCount
from GUI.ViewModel.LineItem import LineItem
from GUI.ViewModel.ViewModelItem import ViewModelItem
from GUI.ViewModel.ViewModelError import ViewModelError

from PySubtitle.Helpers import FormatMessages, UpdateFields
from PySubtitle.SubtitleBatch import SubtitleBatch
from PySubtitle.Translation import Translation
from PySubtitle.TranslationPrompt import TranslationPrompt
from PySubtitle.Helpers.Localization import _

class BatchItem(ViewModelItem):
    """ Represents a subtitle batch in the view model"""
    def __init__(self, scene_number : int, batch : SubtitleBatch, debug_view : bool = False):
        super().__init__(_("Scene {scene}, batch {batch}").format(scene=scene_number, batch=batch.number))
        self.scene: int = scene_number
        self.number: int = batch.number
        self.debug_view: bool = debug_view
        self.lines: dict[int, LineItem] = {}
        self.batch_model: dict[str, Any] = {
            'start': batch.txt_start,
            'end': batch.srt_end,
            'summary': batch.summary,
            'errors': self._get_errors(batch.errors),
            'translated': batch.translation is not None
        }

        # cache on demand
        self._first_line_num: int|None = None
        self._last_line_num: int|None = None

        if batch.translation and isinstance(batch.translation, Translation):
            self.batch_model.update({
                'response': batch.translation.FormatResponse(),
                'reasoning': batch.translation.reasoning,
                'context': batch.context
            })

        if batch.prompt:
            self.batch_model.update({
                'prompt': FormatPrompt(batch.prompt)
            })

            if self.debug_view:
                self.batch_model.update({
                    'messages': FormatMessages(batch.prompt.messages)
                })

        self.setData(self.batch_model, Qt.ItemDataRole.UserRole)

    @property
    def line_count(self) -> int:
        return len(self.lines)

    @property
    def translated_count(self) -> int:
        return len([line for line in self.lines.values() if line.translation is not None])

    @property
    def all_translated(self) -> bool:
        return self.translated_count == self.line_count

    @property
    def translated(self) -> bool:
        return bool(self.batch_model.get('translated', False))

    @property
    def start(self) -> str:
        return self.batch_model['start']

    @property
    def end(self) -> str:
        return self.batch_model['end']

    @property
    def context(self) -> str|None:
        return self.batch_model.get('context')

    @property
    def summary(self) -> str|None:
        return self.batch_model.get('summary')

    @property
    def response(self) -> str|None:
        return self.batch_model.get('response')

    @property
    def prompt(self) -> str|None:
        return self.batch_model.get('prompt')
    
    @property
    def reasoning(self) -> str|None:
        return self.batch_model.get('reasoning')

    @property
    def first_line_number(self) -> int|None:
        if not self._first_line_num:
            self._update_first_and_last()
        return self._first_line_num

    @property
    def last_line_number(self) -> int|None:
        if not self._last_line_num:
            self._update_first_and_last()
        return self._last_line_num

    @property
    def has_errors(self) -> bool:
        return True if self.batch_model.get('errors') else False

    def Update(self, update : dict):
        """
        Update the batch model properties
        """
        if not isinstance(update, dict):
            raise ViewModelError(_("Expected a dictionary, got a {type}").format(type=type(update).__name__))

        UpdateFields(self.batch_model, update, ['number', 'summary', 'context', 'start', 'end'])

        if 'errors' in update.keys():
            self.batch_model['errors'] = self._get_errors(update['errors'])

        if 'translation' in update.keys():
            translation = update['translation']
            if isinstance(translation, Translation):
                self.batch_model.update({
                    'response': translation.FormatResponse(),
                    'reasoning': translation.reasoning
                })

        if 'prompt' in update.keys():
            prompt = update['prompt']
            if isinstance(prompt, TranslationPrompt):
                self.batch_model.update({
                    'prompt': FormatPrompt(prompt)
                })
                if self.debug_view:
                    self.batch_model.update({
                        'messages': FormatMessages(prompt.messages)
                    })

        self.setData(self.batch_model, Qt.ItemDataRole.UserRole)

    def AddLineItem(self, line_number : int, model : dict[str, Any]):
        """
        Add an original line item to the batch
        """
        line_item : LineItem = LineItem(line_number, model)
        last_line_item_qt = self.child(self.rowCount() - 1, 0) if self.rowCount() > 0 else None
        last_line_item = last_line_item_qt if isinstance(last_line_item_qt, LineItem) else None

        if not last_line_item or line_number > last_line_item.number:
            self.appendRow(line_item)
            self.lines[line_number] = line_item
        else:
            for row in range(self.rowCount()):
                row_item_qt = self.child(row, 0)
                if not isinstance(row_item_qt, LineItem):
                    continue
                row_item: LineItem = row_item_qt
                
                if not row_item.number:
                    raise ViewModelError(_("Line item {row} has no line number").format(row=row))

                if row_item.number < line_number:
                    continue

                # Insert the new line at the first opportunity
                if line_item:
                    self.insertRow(row, line_item)
                    self.lines[line_number] = line_item
                    line_item = None  # type: ignore
                    if row_item.number > line_number:
                        # No need to adjust the following line numbers
                        break

                row_item.number = row_item.number + 1
                self.lines[row_item.number] = row_item

        self._invalidate_first_and_last()

    def AddTranslation(self, line_number : int, translation_text : str|None):
        """
        Add a translation to the line item
        """
        if line_number in self.lines.keys():
            line_item : LineItem = self.lines[line_number]
            if translation_text is not None:
                line_item.Update({ 'translation' : translation_text })
        else:
            logging.warning(_("Original line {line} not found in batch {batch}").format(line=line_number, batch=self.number))

    def GetContent(self) -> dict[str, Any]:
        """
        Return a dictionary of interesting batch data for UI display
        """
        errors = self.batch_model.get('errors', [])
        body = "\n".join(e for e in errors) if self.has_errors and errors \
            else self.summary if self.summary \
            else "\n".join([
                _("1 line") if self.line_count == 1 else _("{count} lines").format(count=self.line_count),
                _("{count} translated").format(count=self.translated_count) if self.translated_count > 0 else ""
            ])

        return {
            'heading': _("Batch {num}").format(num=self.number),
            'subheading': _("Lines {first}-{last} ({start} -> {end})").format(first=self.first_line_number, last=self.last_line_number, start=self.start, end=self.end),
            'body': body,
            'footer': DescribeLineCount(self.line_count, self.translated_count),
            'properties': {
                'all_translated' : self.all_translated,
                'errors' : self.has_errors
            }
        }

    def _update_first_and_last(self) -> None:
        line_numbers = [ num for num in self.lines.keys() if num ] if self.lines else None
        self._first_line_num = min(line_numbers) if line_numbers else None
        self._last_line_num = max(line_numbers) if line_numbers else None

    def _invalidate_first_and_last(self) -> None:
        self._first_line_num = None
        self._last_line_num = None

    def _get_errors(self, errors: list[Any]) -> list[str]:
        if errors:
            if all(isinstance(e, str) for e in errors):
                return errors
            elif all(isinstance(e, dict) for e in errors):
                return [ e.get('problem') for e in errors if e.get('problem') ]
            else:
                return [ str(e) for e in errors ]
        return []

    def __str__(self) -> str:
        content = self.GetContent()
        return f"{content['heading']}\n{content['subheading']}\n{content['body']}"


def FormatPrompt(prompt : TranslationPrompt) -> str:
    """
    Format a prompt for display to the user
    """
    if prompt.batch_prompt:
        return prompt.batch_prompt
    else:
        lines = []

        if prompt.user_prompt:
            lines.append(_("User Prompt:\n {text}").format(text=prompt.user_prompt))

        return "\n".join(lines)