import logging
from PySide6.QtCore import QAbstractProxyModel, QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtWidgets import QWidget

from GuiSubtrans.ViewModel.SceneItem import SceneItem
from GuiSubtrans.ViewModel.BatchItem import BatchItem
from GuiSubtrans.ViewModel.LineItem import LineItem
from GuiSubtrans.ViewModel.ViewModel import ProjectViewModel
from GuiSubtrans.ProjectSelection import ProjectSelection
from GuiSubtrans.ViewModel.ViewModelItem import ViewModelItem
from GuiSubtrans.Widgets.Widgets import LineItemView

class SubtitleListModel(QAbstractProxyModel):
    """
    A proxy model that filters subtitle lines to only show selected scenes or batches from the ProjectViewModel.

    The model maintains a list of visible lines based on the selected batches in the ProjectSelection.

    The model maps indices from the proxy model to the source model and vice versa.
    """
    def __init__(self, viewmodel : ProjectViewModel, parent : QWidget|None = None):
        super().__init__(parent)

        self.viewmodel : ProjectViewModel = viewmodel
        self.selected_batch_numbers = []
        self.visible = []
        self.visible_row_map : dict = {}
        self.size_map : dict = {}

        # Connect signals to update mapping when source model changes
        # TODO: investigate whether any other signals on the base model should be handled to trigger a refresh of the proxy model.
        # layoutChanged is a pretty high-level signal that should cover most cases,
        # but perhaps we can be more granular to avoid a complete refresh of the view.
        if self.viewmodel:
            self.setSourceModel(self.viewmodel)
            self.viewmodel.layoutChanged.connect(self._update_visible_batches)
            self.viewmodel.dataChanged.connect(self._on_data_changed)

    def ShowSelection(self, selection : ProjectSelection):
        """
        Update the model to show lines from the selected batches or scenes.

        If no selection is made, show all lines.
        """
        if selection.selected_batches:
            batch_numbers = [(batch.scene, batch.number) for batch in selection.selected_batches]
        elif selection.selected_scenes:
            batch_numbers = selection.batch_numbers
        else:
            batch_numbers = self.viewmodel.GetBatchNumbers()

        if sorted(batch_numbers) != self.selected_batch_numbers:
            self.ShowSelectedBatches(batch_numbers)

    def ShowSelectedBatches(self, batch_numbers : list[tuple[int, int]]):
        """
        Filter the model to only show lines from the selected batches.

        Builds a list of visible lines and a mapping from line numbers to model rows for efficient index mapping.
        """
        self.selected_batch_numbers = sorted(batch_numbers)
        viewmodel = self.viewmodel
        visible = []

        root_item = viewmodel.getRootItem()

        for scene_index in range(0, root_item.rowCount()):
            scene_item = root_item.child(scene_index, 0)
            if not isinstance(scene_item, SceneItem):
                continue

            for batch_index in range (0, scene_item.rowCount()):
                batch_item = scene_item.child(batch_index, 0)
                if not isinstance(batch_item, BatchItem):
                    continue

                if not batch_item or not isinstance(batch_item, BatchItem):
                    logging.error(f"Scene Item {scene_index} has invalid child {batch_index}: {type(batch_item).__name__}")
                    break

                if (scene_item.number, batch_item.number) in batch_numbers:
                    lines = batch_item.lines
                    visible_lines = [ (scene_item.number, batch_item.number, line) for line in lines.keys() ]
                    visible.extend(sorted(visible_lines))

        self.visible = visible
        self.visible_row_map = { item[2] : row for row, item in enumerate(self.visible) }
        self.layoutChanged.emit()

    def mapFromSource(self, source_index : QModelIndex|QPersistentModelIndex):
        item = self.viewmodel.itemFromIndex(source_index)
        if not isinstance(item, ViewModelItem):
            return QModelIndex()

        if isinstance(item, LineItem):
            row = self.visible_row_map.get(item.number, None)
            if row is not None:
                return self.index(row, 0, QModelIndex())

        return QModelIndex()

    def mapToSource(self, index : QModelIndex|QPersistentModelIndex):
        """
        Map an index into the proxy model to the source model
        """
        if not index.isValid():
            return QModelIndex()

        row = index.row()
        if row >= len(self.visible):
            logging.debug(f"Tried to map an unknown row to source model: {row}")
            return QModelIndex()

        key = self.visible[row]
        _, _, line = key

        item = self.viewmodel.GetLineItem(line)
        if item is None:
            return QModelIndex()
        return self.viewmodel.indexFromItem(item)

    def rowCount(self, parent : QModelIndex|QPersistentModelIndex = QModelIndex()):
        if parent.isValid():
            return 0    # Only top-level items in this model

        return len(self.visible)

    def columnCount(self, parent : QModelIndex|QPersistentModelIndex = QModelIndex()):
        return 1

    def index(self, row, column, parent : QModelIndex|QPersistentModelIndex = QModelIndex()):
        """
        Create a model index for the given model row
        """
        if not self.hasIndex(row, column, parent):
            return QModelIndex()

        scene_number, batch_number, line_number = self.visible[row]

        scene_item = self.viewmodel.model.get(scene_number)
        if not scene_item:
            logging.debug(f"Invalid scene number in SubtitleListModel: {scene_number}")
            return QModelIndex()

        batches = scene_item.batches
        if not batch_number in batches.keys():
            logging.debug(f"Invalid batch number in SubtitleListModel ({scene_number},{batch_number})")
            return QModelIndex()

        lines = batches[batch_number].lines

        if line_number not in lines:
            logging.debug(f"Visible subtitles list has invalid line number ({scene_number},{batch_number},{line_number})")
            return QModelIndex()

        line : LineItem = lines[line_number]

        return self.createIndex(row, column, line)

    def data(self, index, role : int = Qt.ItemDataRole.DisplayRole):
        """
        Fetch the data for an index in the proxy model from the source model
        """
        item : LineItem|None = None
        if index.isValid():
            source_index = self.mapToSource(index)
            qItem = self.viewmodel.itemFromIndex(source_index)
            item = qItem if isinstance(qItem, LineItem) else None

            if not item:
                if qItem is not None:
                    logging.debug(f"Invalid item in source model found for index {index.row()}, {index.column()}: {type(qItem).__name__}")
                else:
                    logging.debug(f"No item in source model found for index {index.row()}, {index.column()}")
                return None

        if not item:
            item = LineItem(-1, { 'start' : "0:00:00,000", 'end' : "0:00:00,000",  'text' : "Invalid index" })

        if role == Qt.ItemDataRole.UserRole:
            return item

        if role == Qt.ItemDataRole.DisplayRole:
            return LineItemView(item)

        if role == Qt.ItemDataRole.SizeHintRole:
            if isinstance(item, LineItem) and item.height:
                if item.height in self.size_map:
                    return self.size_map[item.height]
                size = LineItemView(item).sizeHint()
                self.size_map[item.height] = size
                return size
            else:
                return LineItemView(item).sizeHint()

        return None

    def _on_data_changed(self, top_left, bottom_right, roles=None):
        """
        Forward dataChanged signals from ProjectViewModel to SubtitleView
        Map source model indices to proxy model indices using visible_row_map
        """
        # Get the item that changed from the source model
        source_item = self.viewmodel.itemFromIndex(top_left)

        if isinstance(source_item, LineItem):
            # Emit dataChanged for the corresponding index in the proxy model
            proxy_row = self.visible_row_map.get(source_item.number)
            if proxy_row is not None:
                proxy_index = self.index(proxy_row, 0)
                self.dataChanged.emit(proxy_index, proxy_index, roles or [])

        elif isinstance(source_item, BatchItem):
            # When a batch is updated, refresh the visible lines list to force a remap of the indices
            self._update_visible_batches()

    def _update_visible_batches(self):
        """
        Refresh the visible subtitles based on the currently selected batches
        """
        visible_batches = self._get_valid_batches(self.selected_batch_numbers)
        if visible_batches:
            self.ShowSelectedBatches(visible_batches)
        else:
            self.ShowSelection(ProjectSelection())

        self.layoutChanged.emit()

    def _get_valid_batches(self, selected_batch_numbers : list[tuple[int, int]]) -> list[tuple[int, int]]:
        """
        Get valid batch selections, using smart fallbacks if the selected batches are no longer available.
        """
        if not selected_batch_numbers:
            return []

        available_batches = set(self.viewmodel.GetBatchNumbers())

        # No batches available at all... this doesn't bode well
        if not available_batches:
            return []

        # First try to show the originally selected batches
        existing_selections = [batch for batch in selected_batch_numbers if batch in available_batches]
        if existing_selections:
            return existing_selections

        # None of the selected batches exist anymore, find a smart fallback
        max_scene = max(scene_num for scene_num, _ in selected_batch_numbers)

        # Try to select the next scene (where selected content most likely moved)
        next_scene_batches = [(s, b) for s, b in available_batches if s == max_scene + 1]
        if next_scene_batches:
            return next_scene_batches

        # Fallback: all batches from the current scene
        current_scene_batches = [(s, b) for s, b in available_batches if s == max_scene]
        if current_scene_batches:
            return current_scene_batches

        # Last resort: show all available batches
        return sorted(available_batches)

