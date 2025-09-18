from PySide6.QtWidgets import QWidget, QSplitter, QHBoxLayout
from PySide6.QtCore import Qt, Signal
from GuiSubtrans.ProjectActions import ProjectActions
from GuiSubtrans.ProjectDataModel import ProjectDataModel

from GuiSubtrans.ProjectSelection import ProjectSelection
from GuiSubtrans.ProjectToolbar import ProjectToolbar

from GuiSubtrans.Widgets.ScenesView import ScenesView
from GuiSubtrans.Widgets.ContentView import ContentView
from GuiSubtrans.Widgets.ProjectSettings import ProjectSettings

class ModelView(QWidget):
    settingsChanged = Signal(dict)

    def __init__(self, action_handler : ProjectActions, parent=None):
        super().__init__(parent)

        if not isinstance(action_handler, ProjectActions):
            raise Exception("Invalid action handler supplied to ModelView")

        self.action_handler = action_handler

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._toolbar = ProjectToolbar(parent=self, action_handler=action_handler)
        self._toolbar.setVisible(False)
        layout.addWidget(self._toolbar)

        # Scenes & Batches Panel
        self.scenes_view = ScenesView(parent=self)

        # Main Content Area
        self.content_view = ContentView(action_handler=action_handler, parent=self)

        # Project Settings
        self.project_settings = ProjectSettings(action_handler=action_handler, parent=self)
        self.project_settings.hide()
        self.project_settings.settingsChanged.connect(self._on_project_settings_changed, Qt.ConnectionType.QueuedConnection)

        # Splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.project_settings)
        splitter.addWidget(self.scenes_view)
        splitter.addWidget(self.content_view)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 3)

        layout.addWidget(splitter)
        self.setLayout(layout)

        self.scenes_view.onSelection.connect(self._items_selected, Qt.ConnectionType.QueuedConnection)
        self.content_view.onSelection.connect(self._lines_selected, Qt.ConnectionType.QueuedConnection)

        self.scenes_view.onBatchEdited.connect(self._on_batch_edited, Qt.ConnectionType.QueuedConnection)
        self.scenes_view.onSceneEdited.connect(self._on_scene_edited, Qt.ConnectionType.QueuedConnection)

    def SetDataModel(self, datamodel : ProjectDataModel):
        self.SetViewModel(datamodel.viewmodel)
        if datamodel.project:
            self.project_settings.SetDataModel(datamodel)
            self._toolbar.show()
            self._toolbar.show_settings = not datamodel.project_options.get('movie_name', None)

            if self._toolbar.show_settings:
                self.project_settings.OpenSettings()
        else:
            self.project_settings.ClearForm()
            self.project_settings.hide()
            self._toolbar.hide()

    def SetViewModel(self, viewmodel):
        self.content_view.hide()
        self.scenes_view.hide()
        self.content_view.Clear()
        self.scenes_view.Clear()

        if viewmodel is not None:
            self.scenes_view.Populate(viewmodel)
            self.content_view.Populate(viewmodel)
            self.scenes_view.show()
            self.content_view.show()

    def ShowProjectSettings(self, show : bool):
        if show == self.project_settings.isVisible():
            return

        if show:
            self.project_settings.OpenSettings()
            self._toolbar.show_settings = True

        else:
            settings = self.project_settings.GetSettings()
            self._toolbar.show_settings = False
            self.project_settings.hide()
            self.settingsChanged.emit(settings)

    def GetSelection(self) -> ProjectSelection:
        selection = ProjectSelection()
        model = self.scenes_view.model()

        selected_indexes = self.scenes_view.selectionModel().selectedIndexes()
        for index in selected_indexes:
            selection.AppendItem(model, index)

        selected_lines = self.content_view.GetSelectedLines()
        if selected_lines:
            selection.AddSelectedLines(selected_lines)

        return selection

    def _items_selected(self):
        self.content_view.ClearSelectedLines()
        selection : ProjectSelection = self.GetSelection()
        self.content_view.ShowSelection(selection)

    def _lines_selected(self):
        selection : ProjectSelection = self.GetSelection()
        self.content_view.ShowSelection(selection)

    def _on_scene_edited(self, scene_number, scene_model):
        update = {
            'summary' : scene_model.get('summary')
        }
        self.action_handler.UpdateScene(scene_number, update)

    def _on_batch_edited(self, scene, batch_number, batch_model):
        update = {
            'summary' : batch_model.get('summary')
        }
        self.action_handler.UpdateBatch(scene, batch_number, update)

    def _on_project_settings_changed(self, settings : dict):
        self.settingsChanged.emit(settings)
        self.content_view.UpdateSettings(settings)

    def UpdateUiLanguage(self):
        """Refresh texts in child widgets when UI language changes."""
        try:
            self._toolbar.UpdateUiLanguage()

            if self.scenes_view:
                self.scenes_view.UpdateUiLanguage()

            if self.content_view:
                self.content_view.UpdateUiLanguage()

            if self.project_settings:
                self.project_settings.UpdateUiLanguage()

        except Exception:
            pass
