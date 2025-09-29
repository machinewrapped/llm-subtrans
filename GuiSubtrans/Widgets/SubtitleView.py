from PySide6.QtWidgets import QListView, QAbstractItemView
from PySide6.QtCore import Qt, QItemSelectionModel, QItemSelection, Signal, QSignalBlocker
from GuiSubtrans.ViewModel.LineItem import LineItem
from GuiSubtrans.ProjectSelection import ProjectSelection, SelectionLine

from GuiSubtrans.ViewModel.ViewModel import ProjectViewModel
from GuiSubtrans.SubtitleItemDelegate import SubtitleItemDelegate
from GuiSubtrans.SubtitleListModel import SubtitleListModel

class SubtitleView(QListView):
    linesSelected = Signal(list)
    editLine = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setSelectionMode(QListView.SelectionMode.ExtendedSelection)
        self.setSelectionBehavior(QListView.SelectionBehavior.SelectRows)
        self.setSpacing(1)
        self.setContentsMargins(0, 0, 0, 0)

        item_delegate = SubtitleItemDelegate()
        self.setItemDelegate(item_delegate)

        self.doubleClicked.connect(self._on_double_click, Qt.ConnectionType.QueuedConnection)

        # Track previous batch numbers to detect when batch selection changes
        self.previous_batch_numbers = []

    def SetViewModel(self, viewmodel : ProjectViewModel):
        model = SubtitleListModel(viewmodel)
        self.setModel(model)
        self.ShowSelection(ProjectSelection())

    def ShowSelection(self, selection : ProjectSelection):
        model = self.model()

        if model and isinstance(model, SubtitleListModel):
            model.ShowSelection(selection)

            # Reset scroll position if the visible batches have changed
            if self._has_visibility_changed(model) and not self._has_same_first_batch(model):
                self.scrollToTop()

            self.previous_batch_numbers = model.selected_batch_numbers

    def GetSelectedLines(self):
        model = self.model()
        selected_indexes = self.selectedIndexes()
        selected_items = [ model.data(index, Qt.ItemDataRole.UserRole) for index in selected_indexes ]
        selected_lines = [ SelectionLine(item.scene, item.batch, item.number, True) for item in selected_items ]
        return selected_lines

    def ClearSelectedLines(self):
        selection_model = self.selectionModel()
        selection_model.clearSelection()

    def SelectSubtitles(self, line_numbers):
        """
        Select lines with number in the given list
        """
        model = self.model()
        if not model:
            return

        selection_model = self.selectionModel()
        selection_flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
        selected_indexes = []

        with QSignalBlocker(selection_model):
            for row in range(model.rowCount()):
                item_index = model.index(row, 0)
                row_item : LineItem = model.data(item_index, Qt.ItemDataRole.UserRole)
                if isinstance(row_item, LineItem):
                    if row_item.number and row_item.number in line_numbers:
                        selection_model.select(item_index, selection_flags)
                        selected_indexes.append(item_index)

            for index in self.selectedIndexes():
                if index not in selected_indexes:
                    selection_model.select(index, QItemSelectionModel.SelectionFlag.Deselect)

        # Update the viewport to refresh the list view
        self.viewport().update()

    def SelectAll(self):
        """
        Select all lines in the list view
        """
        model = self.model()
        if not model:
            return

        selection_model = self.selectionModel()
        selection_flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows

        with QSignalBlocker(selection_model):
            # Create a selection range that covers all the items in the model
            first_index = model.index(0, 0)
            last_index = model.index(model.rowCount() - 1, 0)
            selection_range = QItemSelection(first_index, last_index)

            # Select the range and update the selection model
            selection_model.select(selection_range, selection_flags)
            self.setSelectionModel(selection_model)

        # Update the viewport to refresh the list view
        self.viewport().update()

    def _on_double_click(self, index):
        model = self.model()
        #TODO: replace the custom double-click subtitle edit widget with inline editor
        item: LineItem = model.data(index, role=Qt.ItemDataRole.UserRole)
        self.editLine.emit(item)

    def selectionChanged(self, selected, deselected):
        super().selectionChanged(selected, deselected)

        qt_model = self.model()
        if not qt_model or not isinstance(qt_model, SubtitleListModel):
            return

        model : SubtitleListModel = qt_model

        selected_lines = []
        selected_indexes = self.selectedIndexes()
        if selected_indexes:
            selected_items = [ model.data(index, role=Qt.ItemDataRole.UserRole) for index in selected_indexes]
            selected_lines = [item for item in selected_items if isinstance(item, LineItem)]

        self.linesSelected.emit(selected_lines)

    def keyPressEvent(self, event):
        """
        Handle keyboard events for the list view
        """
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_A:
            # Ctrl+A pressed, select all items if the list view has focus
            if self.hasFocus():
                self.SelectAll()
        else:
            # Call the base class method to handle other key events
            super().keyPressEvent(event)
   
    def _has_visibility_changed(self, model : SubtitleListModel) -> bool:
        return self.previous_batch_numbers != model.selected_batch_numbers

    def _has_same_first_batch(self, model : SubtitleListModel) -> bool:
        return bool(self.previous_batch_numbers and model.selected_batch_numbers and model.selected_batch_numbers[0] == self.previous_batch_numbers[0])
