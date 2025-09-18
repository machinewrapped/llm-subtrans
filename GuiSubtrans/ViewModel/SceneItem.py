from typing import Any

from GuiSubtrans.ViewModel.BatchItem import BatchItem
from GuiSubtrans.ViewModel.ViewModelError import ViewModelError
from GuiSubtrans.ViewModel.ViewModelItem import ViewModelItem
from GuiSubtrans.GuiHelpers import DescribeLineCount
from PySubtrans.Helpers import UpdateFields
from PySubtrans.SubtitleScene import SubtitleScene
from PySubtrans.Helpers.Localization import _

from PySide6.QtCore import Qt

class SceneItem(ViewModelItem):
    """ Represents a scene in the view model """
    def __init__(self, scene : SubtitleScene):
        super().__init__()
        self.number: int = scene.number
        self.batches: dict[int, BatchItem] = {}
        self.scene_model: dict[str, Any] = {
            'scene': scene.number,
            'start': scene.batches[0].txt_start,
            'end': scene.batches[-1].txt_end,
            'duration': None,
            'gap': None,
            'summary': scene.summary
        }

        # cache on demand
        self._first_line_num: int|None = None
        self._last_line_num: int|None = None

        self.setText(_("Scene {num}").format(num=scene.number))
        self.setData(self.scene_model, Qt.ItemDataRole.UserRole)

    @property
    def batch_count(self) -> int:
        return len(self.batches)

    @property
    def translated_batch_count(self) -> int:
        return sum(1 if batch.translated_count else 0 for batch in self.batches.values())

    @property
    def line_count(self) -> int:
        return sum(batch.line_count for batch in self.batches.values())

    @property
    def translated_count(self) -> int:
        return sum(batch.translated_count for batch in self.batches.values())

    @property
    def all_translated(self) -> bool:
        return bool(self.batches and all(b.all_translated for b in self.batches.values()))

    @property
    def first_line_number(self) -> int|None:
        if not self.batches:
            return None

        batch_number = sorted(self.batches.keys())[0]
        return self.batches[batch_number].first_line_number if self.batches else None

    @property
    def last_line_number(self) -> int|None:
        if not self.batches:
            return None

        batch_number = sorted(self.batches.keys())[-1]
        return self.batches[batch_number].last_line_number if self.batches else None

    @property
    def has_errors(self) -> bool:
        return bool(self.batches and any(b.has_errors for b in self.batches.values()))

    @property
    def start(self) -> str:
        return self.scene_model['start']

    @property
    def end(self) -> str:
        return self.scene_model['end']

    @property
    def duration(self) -> Any:
        return self.scene_model['duration']

    @property
    def summary(self) -> str|None:
        return self.scene_model['summary']

    def AddBatchItem(self, batch_item : BatchItem) -> None:
        """ Insert or append a batch item to the scene """
        if batch_item.number > len(self.batches):
            self.appendRow(batch_item)
        else:
            self.insertRow(batch_item.number - 1, batch_item)

        self.Remap()
        self.UpdateStartAndEnd()

    def Update(self, update: dict[str, Any]) -> None:
        """ Update the scene model with new data """
        if not isinstance(update, dict):
            raise ViewModelError(f"Expected a dictionary, got a {type(update).__name__}")

        UpdateFields(self.scene_model, update, ['summary', 'start', 'end', 'duration', 'gap'])

    def UpdateStartAndEnd(self) -> None:
        """ Update the start and end times of the scene """
        start = None
        end = None
        for i in range(0, self.rowCount()):
            batch_item = self.child(i, 0)
            if not isinstance(batch_item, BatchItem):
                continue
            if i == 0:
                start = batch_item.start
            end = batch_item.end

        if start:
            self.scene_model['start'] = start
        if end:
            self.scene_model['end'] = end

    def Remap(self) -> None:
        """ Rebuild the batch number map """
        batch_items = {}
        for i in range(0, self.rowCount()):
            batch_item = self.child(i, 0)
            if not isinstance(batch_item, BatchItem):
                continue
            batch_item.number = i + 1
            batch_items[batch_item.number] = batch_item

        self.batches = batch_items

    def GetContent(self) -> dict[str, Any]:
        """ Return a dictionary of interesting scene data for UI display """
        str_translated = _("All batches translated") if self.translated_batch_count == self.batch_count else _("{done} of {total} batches translated").format(done=self.translated_batch_count, total=self.batch_count)
        metadata = [
            _("1 line") if self.line_count == 1 else _("{lines} lines in {batches} batches").format(lines=self.line_count, batches=self.batch_count),
            str_translated if self.translated_batch_count > 0 else None,
        ]

        return {
            'heading': _("Scene {num}").format(num=self.number),
            'subheading': _("Lines {first}-{last} ({start} -> {end})").format(first=self.first_line_number, last=self.last_line_number, start=self.start, end=self.end),
            'body': self.summary if self.summary else "\n".join([data for data in metadata if data is not None]),
            'footer': DescribeLineCount(self.line_count, self.translated_count),
            'properties': {
                'all_translated' : self.all_translated,
                'errors' : self.has_errors
            }
        }

    def __str__(self) -> str:
        content = self.GetContent()
        return f"{content['heading']}\n{content['subheading']}\n{content['body']}"