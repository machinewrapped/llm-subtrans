from __future__ import annotations
import logging
import os
from datetime import timedelta
from collections.abc import Callable
from PySide6.QtCore import Qt, QModelIndex, QRecursiveMutex, QMutexLocker, Signal
from PySide6.QtGui import QStandardItemModel, QStandardItem

from GuiSubtrans.ViewModel.BatchItem import BatchItem
from GuiSubtrans.ViewModel.LineItem import LineItem
from GuiSubtrans.ViewModel.SceneItem import SceneItem
from GuiSubtrans.ViewModel.ViewModelError import ViewModelError

from PySubtrans.Helpers.Time import GetTimeDelta, TimedeltaToText
from PySubtrans.Instructions import DEFAULT_TASK_TYPE
from PySubtrans.Subtitles import Subtitles
from PySubtrans.SubtitleScene import SubtitleScene
from PySubtrans.SubtitleBatch import SubtitleBatch
from PySubtrans.SubtitleLine import SubtitleLine
from PySubtrans.Helpers.Localization import _

class ProjectViewModel(QStandardItemModel):
    updatesPending = Signal()

    def __init__(self):
        super().__init__()
        self.model : dict[int, SceneItem] = {}
        self.updates : list[Callable[[ProjectViewModel], None]] = []
        self.update_lock = QRecursiveMutex()
        self.debug_view : bool = os.environ.get("DEBUG_MODE") == "1"
        self.task_type : str = DEFAULT_TASK_TYPE

    def getRootItem(self) -> QStandardItem:
        return self.invisibleRootItem()

    def AddUpdate(self, update : Callable[[ProjectViewModel], None]) -> None:
        """ Add an update to the queue and signal the main thread to process it """
        with QMutexLocker(self.update_lock):
            self.updates.append(update)
        self.updatesPending.emit()

    def ProcessUpdates(self):
        """ While there are updates in the queue, process them in sequence """
        while True:
            with QMutexLocker(self.update_lock):
                # Pop the next update from the queue until there are none left
                if not self.updates:
                    break

                update = self.updates.pop(0)

            try:
                logging.debug(f"Processing viewmodel update")
                self.ApplyUpdate(update)

            except Exception as e:
                logging.error(f"Error updating view model: {e}")
                # break?

        self.layoutChanged.emit()

    def ApplyUpdate(self, update_function : Callable[[ProjectViewModel], None]) -> None:
        """
        Patch the viewmodel
        """
        if not callable(update_function):
            raise ViewModelError(f"Expected a callable, got a {type(update_function).__name__}")

        # TODO: Don't reset the model if it can be avoided
        self.beginResetModel()
        self.blockSignals(True)

        try:
            update_function(self)

        except Exception as e:
            logging.error(f"Error updating viewmodel: {e}")

        finally:
            self.Remap()
            self.blockSignals(False)
            self.endResetModel()

    def CreateModel(self, data : Subtitles):
        if not isinstance(data, Subtitles):
            raise ValueError(_("Can only model subtitle files"))

        self.model = {}
        self.task_type = data.task_type

        for scene in data.scenes:
            scene_item = self.CreateSceneItem(scene)
            self.model[scene.number] = scene_item
            self.getRootItem().appendRow(scene_item)

    def CreateSceneItem(self, scene : SubtitleScene) -> SceneItem:
        scene_item = SceneItem(scene)

        for batch in scene.batches:
            batch_item : BatchItem = self.CreateBatchItem(scene.number, batch)
            scene_item.AddBatchItem(batch_item)

        return scene_item

    def CreateBatchItem(self, scene_number : int, batch : SubtitleBatch) -> BatchItem:
        batch_item = BatchItem(scene_number, batch, debug_view=self.debug_view)

        gap_start = None
        for line in batch.originals:
            batch_item.AddLineItem(line.number, {
                'scene': scene_number,
                'batch': batch.number,
                'start': line.txt_start,
                'end': line.srt_end,
                'duration': line.txt_duration,
                'gap': TimedeltaToText(line.start - gap_start) if gap_start else "",
                'text': line.text,
                'style': line.metadata.get('style')
            })

            gap_start = line.end

        if batch.translated:
            for line in batch.translated:
                batch_item.AddTranslation(line.number, line.text if line.text else None)

        return batch_item

    def GetLineItem(self, line_number : int) -> LineItem|None:
        """ Find a line item in the viewmodel """
        if not line_number:
            return None

        root_item = self.getRootItem()
        for scene_row in range(0, root_item.rowCount()):
            scene_item_qt = root_item.child(scene_row, 0)
            if not isinstance(scene_item_qt, SceneItem):
                logging.error(f"Expected SceneItem at row {scene_row}, got {type(scene_item_qt).__name__}")
                continue
            scene_item: SceneItem = scene_item_qt
            for batch_row in range(0, scene_item.rowCount()):
                batch_item_qt = scene_item.child(batch_row, 0)
                if not isinstance(batch_item_qt, BatchItem):
                    logging.error(f"Expected BatchItem at scene {scene_item.number} row {batch_row}, got {type(batch_item_qt).__name__}")
                    continue
                batch_item: BatchItem = batch_item_qt
                first_line = batch_item.first_line_number
                if first_line is not None and first_line > line_number:
                    return None

                for line_row in range(0, batch_item.rowCount()):
                    line_item_qt = batch_item.child(line_row, 0)
                    if not isinstance(line_item_qt, LineItem):
                        logging.error(f"Expected LineItem at scene {scene_item.number} batch {batch_item.number} row {line_row}, got {type(line_item_qt).__name__}")
                        continue
                    line_item: LineItem = line_item_qt
                    if line_item.number == line_number:
                        return line_item

    def GetBatchNumbers(self):
        """
        Get all batch numbers for the model
        """
        batch_numbers = []
        for scene_item in self.model.values():
            for batch_item in scene_item.batches.values():
                batch_numbers.append((batch_item.scene, batch_item.number))
        return batch_numbers

    def Remap(self):
        """
        Rebuild the dictionary keys for the model
        """
        root_item = self.getRootItem()
        scene_items: list[SceneItem] = []
        for i in range(0, root_item.rowCount()):
            scene_item = root_item.child(i, 0)
            if isinstance(scene_item, SceneItem):
                scene_items.append(scene_item)
            else:
                logging.error(f"Expected SceneItem during remap at row {i}, got {type(scene_item).__name__}")
        self.model = { item.number: item for item in scene_items }

        for scene_item in scene_items:
            batch_items: list[BatchItem] = []
            for i in range(0, scene_item.rowCount()):
                batch_item = scene_item.child(i, 0)
                if isinstance(batch_item, BatchItem):
                    batch_items.append(batch_item)
                else:
                    logging.error(f"Expected BatchItem during remap at scene {scene_item.number} row {i}, got {type(batch_item).__name__}")

            for batch_number, batch_item in enumerate(batch_items, start=1):
                if batch_item.scene != scene_item.number or batch_item.number != batch_number:
                    logging.debug(f"Batch ({batch_item.scene}, {batch_item.number}) -> ({scene_item.number},{batch_item.number})")
                    batch_item.scene = scene_item.number
                    batch_item.number = batch_number

            scene_item.batches = { item.number: item for item in batch_items }

            for batch_item in batch_items:
                line_items: list[LineItem] = []
                for i in range(0, batch_item.rowCount()):
                    line_item = batch_item.child(i, 0)
                    if isinstance(line_item, LineItem):
                        line_items.append(line_item)
                    else:
                        logging.error(f"Expected LineItem during remap at scene {scene_item.number} batch {batch_item.number} row {i}, got {type(line_item).__name__}")

                for line_item in line_items:
                    if line_item.scene != scene_item.number or line_item.batch != batch_item.number:
                        # logging.debug(f"Batch ({line_item.scene},{line_item.batch}) Line {line_item.number} -> Batch ({scene_item.number},{batch_item.number})")
                        line_item.line_model['scene'] = scene_item.number
                        line_item.line_model['batch'] = batch_item.number

                batch_item.lines = { item.number: item for item in line_items }

    #############################################################################

    def AddScene(self, scene : SubtitleScene):
        logging.debug(f"Adding scene {scene.number}")
        if not isinstance(scene, SubtitleScene):
            raise ViewModelError(f"Wrong type for AddScene ({type(scene).__name__})")

        scene_item = self.CreateSceneItem(scene)

        root_item = self.getRootItem()
        insert_row = scene_item.number - 1

        self.beginInsertRows(QModelIndex(), insert_row, insert_row)
        if insert_row >= root_item.rowCount():
            root_item.appendRow(scene_item)
        else:
            root_item.insertRow(insert_row, scene_item)
            for i in range(0, self.rowCount()):
                child = root_item.child(i, 0)
                if isinstance(child, SceneItem):
                    child.number = i + 1

        scene_items = []
        for i in range(0, root_item.rowCount()):
            child = root_item.child(i, 0)
            if isinstance(child, SceneItem):
                scene_items.append(child)
            else:
                logging.error(f"Expected SceneItem during AddScene at row {i}, got {type(child).__name__}")
        self.model = {item.number: item for item in scene_items}

        self.endInsertRows()

    def ReplaceScene(self, scene : SubtitleScene):
        logging.debug(f"Replacing scene {scene.number}")
        if not isinstance(scene, SubtitleScene):
            raise ViewModelError(f"Wrong type for ReplaceScene ({type(scene).__name__})")

        root_item = self.getRootItem()
        scene_item = self.CreateSceneItem(scene)
        scene_index = self.indexFromItem(self.model[scene.number])

        row = scene_index.row()
        self.beginRemoveRows(QModelIndex(), row, row)
        root_item.removeRow(row)
        self.endRemoveRows()

        self.beginInsertRows(QModelIndex(), row, row)
        root_item.insertRow(row, scene_item)
        self.model[scene.number] = scene_item
        self.endInsertRows()

        self.getRootItem().emitDataChanged()

    def UpdateScene(self, scene_number: int, scene_update : dict) -> bool:
        logging.debug(f"Updating scene {scene_number}")
        scene_item = self.model.get(scene_number)
        if not scene_item:
            raise ViewModelError(f"Model update for unknown scene {scene_number}")

        scene_item.Update(scene_update)

        if scene_update.get('number'):
            scene_item.number = scene_update['number']

        if scene_update.get('batches'):
            for batch_number, batch_update in scene_update['batches'].items():
                self.UpdateBatch(scene_number, batch_number, batch_update)

        scene_index = self.indexFromItem(scene_item)
        self.setData(scene_index, scene_item, Qt.ItemDataRole.UserRole)

        return True

    def RemoveScene(self, scene_number: int) -> None:
        logging.debug(f"Removing scene {scene_number}")
        if scene_number not in self.model.keys():
            raise ViewModelError(f"Scene number {scene_number} does not exist")

        root_item = self.getRootItem()
        scene_item = self.model.get(scene_number)
        if not scene_item:
            return
        scene_index = self.indexFromItem(scene_item)

        self.beginRemoveRows(QModelIndex(), scene_index.row(), scene_index.row())
        root_item.removeRow(scene_index.row())
        del self.model[scene_number]
        self.endRemoveRows()

    #############################################################################

    def AddBatch(self, batch : SubtitleBatch) -> None:
        logging.debug(f"Adding new batch ({batch.scene}, {batch.number})")
        if not isinstance(batch, SubtitleBatch):
            raise ViewModelError(f"Wrong type for AddBatch ({type(batch).__name__})")

        batch_item : BatchItem = self.CreateBatchItem(batch.scene, batch)

        scene_item = self.model.get(batch.scene)
        if not scene_item:
            raise ViewModelError(f"Scene {batch.scene} not found")

        scene_index = self.indexFromItem(scene_item)
        insert_row = batch_item.number - 1

        self.beginInsertRows(scene_index, insert_row, insert_row)
        scene_item.AddBatchItem(batch_item)
        self.endInsertRows()

        scene_item.emitDataChanged()

    def ReplaceBatch(self, batch):
        logging.debug(f"Replacing batch ({batch.scene}, {batch.number})")
        if not isinstance(batch, SubtitleBatch):
            raise ViewModelError(f"Wrong type for ReplaceBatch ({type(batch).__name__})")

        scene_item : SceneItem = self.model[batch.scene]
        scene_index = self.indexFromItem(scene_item)
        batch_index = self.indexFromItem(scene_item.batches[batch.number])

        self.beginRemoveRows(scene_index, batch_index.row(), batch_index.row())
        scene_item.removeRow(batch_index.row())
        self.endRemoveRows()

        batch_item : BatchItem = self.CreateBatchItem(batch.scene, batch)

        self.beginInsertRows(scene_index, batch_index.row(), batch_index.row())
        scene_item.insertRow(batch_index.row(), batch_item)
        self.endInsertRows()

        scene_item.batches[batch.number] = batch_item
        scene_item.emitDataChanged()

    def UpdateBatch(self, scene_number: int, batch_number: int, batch_update : dict) -> bool:
        logging.debug(f"Updating batch ({scene_number}, {batch_number})")
        if not isinstance(batch_update, dict):
            raise ViewModelError(_("Expected a patch dictionary"))

        scene_item = self.model.get(scene_number)
        if not scene_item:
            logging.error(f"Model update for unknown batch, scene {scene_number} batch {batch_number}")
            return False
            
        batch_item = scene_item.batches.get(batch_number)
        if not batch_item:
            logging.error(f"Model update for unknown batch, scene {scene_number} batch {batch_number}")
            return False

        batch_item.Update(batch_update)

        if batch_update.get('number'):
            batch_item.number = batch_update['number']

        if batch_update.get('lines'):
            self.UpdateLines(scene_number, batch_number, batch_update['lines'])

        batch_index = self.indexFromItem(batch_item)
        self.setData(batch_index, batch_item, Qt.ItemDataRole.UserRole)

        scene_item.emitDataChanged()
        return True

    def RemoveBatch(self, scene_number: int, batch_number: int) -> None:
        logging.debug(f"Removing batch ({scene_number}, {batch_number})")
        scene_item = self.model.get(scene_number)
        if not scene_item:
            raise ViewModelError(f"Scene {scene_number} not found")

        if batch_number not in scene_item.batches.keys():
            raise ViewModelError(f"Scene {scene_number} batch {batch_number} does not exist")

        scene_index = self.indexFromItem(scene_item)

        for i in range(0, scene_item.rowCount()):
            batch_child = scene_item.child(i, 0)
            if not isinstance(batch_child, BatchItem):
                logging.error(f"Expected BatchItem during RemoveBatch at scene {scene_number} row {i}, got {type(batch_child).__name__}")
                continue
            batch_item: BatchItem = batch_child
            if batch_item.number == batch_number:
                self.beginRemoveRows(scene_index, i, i)
                scene_item.removeRow(i)
                self.endRemoveRows()
                logging.debug(f"Removed row {i} from scene {scene_item.number}, rowCount={scene_item.rowCount()}")
                break

        scene_item.Remap()
        scene_item.UpdateStartAndEnd()

    #############################################################################

    def AddLine(self, scene_number: int, batch_number: int, line : SubtitleLine) -> None:
        if not isinstance(line, SubtitleLine):
            raise ViewModelError(f"Wrong type for AddLine ({type(line).__name__})")

        logging.debug(f"Adding line ({scene_number}, {batch_number}, {line.number})")

        scene_item = self.model.get(scene_number)
        if not scene_item:
            raise ViewModelError(f"Scene {scene_number} not found")
        batch_item : BatchItem = scene_item.batches[batch_number]
        if line.number in batch_item.lines.keys():
            raise ViewModelError(f"Line {line.number} already exists in {scene_number} batch {batch_number}")

        gap_duration = timedelta(seconds=0)
        previous_line_number = max((existing_number for existing_number in batch_item.lines.keys() if existing_number < line.number), default=None)
        if previous_line_number is not None:
            previous_line_item = batch_item.lines.get(previous_line_number)
            if isinstance(previous_line_item, LineItem):
                previous_end = GetTimeDelta(previous_line_item.end, raise_exception=False)
                if isinstance(previous_end, Exception):
                    logging.error(
                        f"Unable to parse end time for line {previous_line_number} in scene {scene_number} batch {batch_number}: {previous_line_item.end}"
                    )
                elif isinstance(previous_end, timedelta):
                    gap_duration = line.start - previous_end
            else:
                logging.error(
                    f"Expected LineItem for line {previous_line_number} in scene {scene_number} batch {batch_number}, got {type(previous_line_item).__name__ if previous_line_item is not None else 'None'}"
                )

        self.beginInsertRows(self.indexFromItem(batch_item), line.number - 1, line.number - 1)
        batch_item.AddLineItem(line.number, {
                'scene': scene_number,
                'batch': batch_number,
                'start': line.txt_start,
                'end': line.srt_end,
                'duration': line.txt_duration,
                'gap': TimedeltaToText(gap_duration),
                'text': line.text,
                'style': line.metadata.get('style')
            })

        if line.translation:
            batch_item.AddTranslation(line.number, line.translation)

        self.endInsertRows()

    def UpdateLine(self, scene_number : int, batch_number : int, line_number : int, line_update : dict) -> None:
        logging.debug(f"Updating line ({scene_number}, {batch_number}, {line_number})")
        if not isinstance(line_update, dict):
            raise ViewModelError(_("Expected a patch dictionary"))

        scene_item = self.model.get(scene_number)
        if not scene_item:
            raise ViewModelError(f"Scene {scene_number} not found")
        batch_item : BatchItem = scene_item.batches[batch_number]
        if line_number not in batch_item.lines.keys():
            raise ViewModelError(f"Line {line_number} not found in {scene_number} batch {batch_number}")

        line_item : LineItem = batch_item.lines[line_number]
        line_item.Update(line_update)

    def UpdateLines(self, scene_number : int, batch_number : int, lines : dict) -> None:
        logging.debug(f"Updating lines in ({scene_number}, {batch_number})")
        scene_item = self.model.get(scene_number)
        if not scene_item:
            raise ViewModelError(f"Scene {scene_number} not found")
        batch_item = scene_item.batches.get(batch_number)
        if not batch_item:
            raise ViewModelError(f"Batch {batch_number} not found in scene {scene_number}")
        for line_number, line_update in lines.items():
            line_item = batch_item.lines.get(line_number)
            if line_item:
                line_item.Update(line_update)
            else:
                line = SubtitleLine({
                    'number' : line_number,
                    'start' : line_update.get('start'),
                    'end' : line_update.get('end'),
                    'body' : line_update.get('text'),
                })
                line.translation = line_update.get('translation')
                self.AddLine(scene_number, batch_number, line)

    def RemoveLine(self, scene_number: int, batch_number: int, line_number: int) -> None:
        logging.debug(f"Removing line ({scene_number}, {batch_number}, {line_number})")

        scene_item = self.model.get(scene_number)
        if not scene_item:
            raise ViewModelError(f"Scene {scene_number} not found")
        batch_item : BatchItem = scene_item.batches[batch_number]
        if line_number not in batch_item.lines.keys():
            raise ViewModelError(f"Line {line_number} not found in {scene_number} batch {batch_number}")

        line_item = batch_item.lines[line_number]
        line_index = self.indexFromItem(line_item)
        batch_item.removeRow(line_index.row())

        del batch_item.lines[line_number]

        batch_item.emitDataChanged()

    def RemoveLines(self, scene_number: int, batch_number: int, line_numbers: list[int]) -> None:
        logging.debug(f"Removing lines in ({scene_number}, {batch_number})")

        unfound_lines = []
        scene_item = self.model.get(scene_number)
        if not scene_item:
            raise ViewModelError(f"Scene {scene_number} not found")
        batch_item = scene_item.batches.get(batch_number)
        if not batch_item:
            raise ViewModelError(f"Batch {batch_number} not found in scene {scene_number}")
        for line_number in reversed(line_numbers):
            if line_number in batch_item.lines.keys():
                line_item = batch_item.lines[line_number]
                line_index = self.indexFromItem(line_item)
                batch_item.removeRow(line_index.row())

                del batch_item.lines[line_number]

            else:
                unfound_lines.append(line_number)

        if unfound_lines:
            logging.warning(_("Lines {lines} not found in batch {batch}").format(lines=unfound_lines, batch=batch_number))

        batch_item.emitDataChanged()

