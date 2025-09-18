import logging
from PySide6.QtWidgets import QVBoxLayout, QWidget, QDialog
from PySide6.QtCore import Qt, Signal, Slot
from GuiSubtrans.ProjectActions import ProjectActions
from GuiSubtrans.ViewModel.LineItem import LineItem
from GuiSubtrans.ProjectSelection import ProjectSelection
from GuiSubtrans.ViewModel.ViewModel import ProjectViewModel
from GuiSubtrans.Widgets.Editors import EditSubtitleDialog
from GuiSubtrans.Widgets.SelectionView import SelectionView

from GuiSubtrans.Widgets.SubtitleView import SubtitleView
from PySubtrans.Instructions import DEFAULT_TASK_TYPE

class ContentView(QWidget):
    """
    The main content view for the application. This view is responsible for displaying the subtitle lines and the selection view.
    """
    onSelection = Signal()

    def __init__(self, action_handler : ProjectActions, parent=None):
        super().__init__(parent)

        if not isinstance(action_handler, ProjectActions):
            raise Exception("Invalid action handler supplied to ContentView")

        self.action_handler = action_handler
        self.viewmodel = None

        self.subtitle_view = SubtitleView(parent=self)

        self.selection_view = SelectionView(action_handler=action_handler, parent=self)
        self.selection_view.resetSelection.connect(self.ClearSelectedLines)

        # connect the selection handlers
        self.subtitle_view.linesSelected.connect(self._lines_selected)

        # connect the editors
        self.subtitle_view.editLine.connect(self._edit_line)

        layout = QVBoxLayout()
        layout.addWidget(self.subtitle_view)
        layout.addWidget(self.selection_view)
        self.setLayout(layout)

    def ShowSelection(self, selection : ProjectSelection):
        if selection.AnyScenes() or selection.AnyBatches():
            self.subtitle_view.ShowSelection(selection)
        self.selection_view.ShowSelection(selection)

    def Populate(self, viewmodel : ProjectViewModel):
        self.viewmodel = viewmodel
        self.viewmodel.updatesPending.connect(self._update_view_model, type=Qt.ConnectionType.QueuedConnection)
        self.subtitle_view.SetViewModel(viewmodel)
        self.selection_view.SetTaskType(viewmodel.task_type)
        self.selection_view.ShowSelection(ProjectSelection())

    def Clear(self):
        self.viewmodel = ProjectViewModel()
        self.subtitle_view.SetViewModel(self.viewmodel)
        self.selection_view.ShowSelection(ProjectSelection())

    def UpdateSettings(self, settings : dict):
        if 'task_type' in settings:
            task_type = settings.get('task_type', DEFAULT_TASK_TYPE)
            self.selection_view.SetTaskType(task_type)

    def GetSelectedLines(self):
        return self.subtitle_view.GetSelectedLines()

    def ClearSelectedLines(self):
        self.subtitle_view.ClearSelectedLines()

    def _lines_selected(self, originals):
        self.onSelection.emit()

    def _edit_line(self, item : LineItem):
        #TODO: replace the custom double-click subtitle edit widget with inline edit
        if not isinstance(item, LineItem):
            raise Exception("Double-clicked something unexpected")

        if not item.number:
            logging.error("Can't identify the line number")

        dialog = EditSubtitleDialog(item)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            if dialog.model:
                original_text = dialog.model.get('original')
                translated_text = dialog.model.get('translated')
                if not translated_text and not dialog.model.get('was_translated'):
                    translated_text = None

                self.action_handler.UpdateLine(item.number, original_text, translated_text)

    @Slot()
    def _update_view_model(self):
        if self.viewmodel:
            self.viewmodel.ProcessUpdates()

    def UpdateUiLanguage(self):
        """Refresh texts in contained views/editors for new UI language."""
        if self.viewmodel:
            try:
                self.selection_view.UpdateUiLanguage()
                self.Populate(self.viewmodel)

            except Exception as ex:
                logging.error(f"Error updating selection view language: {ex}")

