import logging
import os

from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtWidgets import QFileDialog, QApplication, QMainWindow

from GUI.Command import Command, CommandError
from GUI.CommandQueue import CommandQueue

from GUI.Commands.AutoSplitBatchCommand import AutoSplitBatchCommand
from GUI.Commands.DeleteLinesCommand import DeleteLinesCommand
from GUI.Commands.EditBatchCommand import EditBatchCommand
from GUI.Commands.EditLineCommand import EditLineCommand
from GUI.Commands.EditSceneCommand import EditSceneCommand
from GUI.Commands.MergeBatchesCommand import MergeBatchesCommand
from GUI.Commands.MergeLinesCommand import MergeLinesCommand
from GUI.Commands.MergeScenesCommand import MergeScenesCommand
from GUI.Commands.ReparseTranslationsCommand import ReparseTranslationsCommand
from GUI.Commands.StartTranslationCommand import StartTranslationCommand
from GUI.Commands.SplitBatchCommand import SplitBatchCommand
from GUI.Commands.SplitSceneCommand import SplitSceneCommand
from GUI.Commands.SwapTextAndTranslations import SwapTextAndTranslations
from GUI.GUICommands import CheckProviderSettings

from GUI.ProjectDataModel import ProjectDataModel
from GUI.ProjectSelection import ProjectSelection

from PySubtitle.Options import Options
from PySubtitle.SubtitleProject import SubtitleProject
from PySubtitle.Helpers.Localization import _

class ActionError(Exception):
    def __init__(self, message, error = None):
        super().__init__(message)
        self.error = error

    def __str__(self) -> str:
        if self.error:
            return str(self.error)
        return super().__str__()

class ProjectActions(QObject):
    actionError = Signal(object)
    saveSettings = Signal()
    showSettings = Signal()
    showProviderSettings = Signal()
    showProjectSettings = Signal(bool)
    showAboutDialog = Signal()
    loadProject = Signal(str, bool)
    saveProject = Signal(str)
    exitProgram = Signal()

    def __init__(self, command_queue : CommandQueue, datamodel : ProjectDataModel|None = None, mainwindow : QMainWindow|None = None):
        super().__init__()

        if not isinstance(command_queue, CommandQueue):
            raise ValueError("Must provide a valid command queue")

        self._mainwindow = mainwindow
        self._command_queue = command_queue
        self.datamodel = datamodel
        self.last_used_path : str|None = None
        if datamodel and datamodel.project and datamodel.project.projectfile:
            self.last_used_path = os.path.dirname(datamodel.project.projectfile)

    def SetDataModel(self, datamodel : ProjectDataModel):
        self.datamodel = datamodel

    def QueueCommand(self, command : Command, callback = None, undo_callback = None):
        """
        Add a command to the command queue and kick the queue to start processing
        """
        command.SetDataModel(self.datamodel)
        command.callback = callback or command.callback
        command.undo_callback = undo_callback or command.undo_callback
        self._command_queue.AddCommand(command)

    def ExecuteCommandNow(self, command : Command):
        """
        Execute a command immediately
        """
        command.SetDataModel(self.datamodel)
        self._command_queue.ExecuteCommand(command)

    def UndoLastCommand(self):
        """
        Undo the last command
        """
        if self._command_queue.has_running_commands:
            logging.debug("No undo while commands are running")
            return

        if not self._command_queue.can_undo:
            logging.error(_("Cannot undo the last command"))
            return

        try:
            self._command_queue.UndoLastCommand()

        except Exception as e:
            logging.error(_("Error undoing the last command: {error}").format(error=str(e)))
            self._command_queue.ClearUndoStack()

    def RedoLastCommand(self):
        """
        Redo the last command
        """
        if self._command_queue.has_running_commands:
            logging.debug("No redo while commands are running")
            return

        if not self._command_queue.can_redo:
            logging.error(_("Cannot redo the last command"))
            return

        try:
            self._command_queue.RedoLastCommand()

        except Exception as e:
            logging.error(_("Error redoing the last command: {error}").format(error=str(e)))
            self._command_queue.ClearRedoStack()

    def LoadProject(self):
        """
        Load a subtitle file
        """
        initial_path = self.last_used_path or os.getcwd()
        shift_pressed = self._is_shift_pressed()

        filters = f"{_('Subtitle files')} (*.srt *.subtrans);;{_('All Files')} (*)"
        filepath, dummy = QFileDialog.getOpenFileName(parent=self._mainwindow, caption=_("Open File"), dir=initial_path, filter=filters) # type: ignore[unused-ignore]

        if filepath:
            self.loadProject.emit(filepath, shift_pressed)

    def SaveProject(self):
        """
        Save the current project
        """
        project : SubtitleProject|None = self.datamodel.project if self.datamodel else None
        if not project:
            raise ActionError(_("Nothing to save!"))

        self.saveSettings.emit()

        #TODO: if project.use_project_file is false, open a dialog with subtitle file filters and call SaveTranslation instead        

        filepath = project.projectfile
        show_dialog = self._is_shift_pressed()

        if show_dialog or not filepath or not os.path.exists(filepath):
            base_path = self.last_used_path or os.getcwd()
            base_name = os.path.basename(project.projectfile) if project.projectfile else "untitled.subtrans"
            filepath = os.path.join(base_path, base_name)
            if project.use_project_file:
                filters = f"{_('Subtrans projects')} (*.subtrans);;{_('All Files')} (*)"
            else:
                filters = f"{_('Subtitle files')} (*.srt);;{_('All Files')} (*)"

            title = _("Save Project File") if project.use_project_file else _("Save Translation")

            filepath, dummy = QFileDialog.getSaveFileName(self._mainwindow, title, filepath, filters)  # type: ignore[unused-ignore]

        if filepath:
            self.saveProject.emit(filepath)

    def CheckProviderSettings(self, options : Options|None = None):
        """
        Check if the translation provider is configured correctly.
        """
        def callback(cmd : Command):
            if not isinstance(cmd, CheckProviderSettings):
                raise CommandError("Invalid command type in callback", cmd)
                
            if cmd.show_provider_settings:
                self.showProviderSettings.emit()
            else:
                logging.info(_("Provider settings validated"))

        if not options:
            options = self.datamodel.project_options if self.datamodel else Options()

        command = CheckProviderSettings(options)
        command.callback = callback
        self.QueueCommand(command)

    def ShowProjectSettings(self, show : bool = True):
        self._validate_datamodel()
        if self.datamodel and not show:
            self.datamodel.SaveProject()

        self.showProjectSettings.emit(show)

    def StartTranslating(self):
        """
        Start or resume translation of the project
        """
        self._validate_datamodel()

        self.saveSettings.emit()

        resume = not self._is_shift_pressed()

        self.QueueCommand(StartTranslationCommand(resume=resume, multithreaded=False))

    def StartTranslatingFast(self):
        """
        Start or resume translation of the project using multiple threads
        """
        self._validate_datamodel()

        self.saveSettings.emit()

        resume = not self._is_shift_pressed()

        self.QueueCommand(StartTranslationCommand(resume=resume, multithreaded=True))

    def StopTranslating(self):
        """
        Stop the translation process
        """
        self._command_queue.Stop()

    def TranslateSelection(self, selection : ProjectSelection):
        """
        Request translation of selected scenes and batches
        """
        if not selection.Any():
            raise ActionError(_("Nothing selected to translate"))

        self._validate_datamodel()

        logging.debug(f"Translate selection of {str(selection)}")

        self.saveSettings.emit()

        if not self.datamodel:
            raise ActionError(_("No datamodel provided"))

        multithreaded = len(selection.scenes) > 1 and self.datamodel.allow_multithreaded_translation

        scenes = { scene.number : {} for scene in selection.selected_scenes }

        for scene in selection.scenes.values():
            line_numbers = [ line.number for line in selection.selected_lines if line.scene == scene.number ]

            if line_numbers:
                # Extract unique batch numbers from the selected lines
                batch_numbers = list(set([ line.batch for line in selection.selected_lines if line.scene == scene.number ]))
            else:
                batch_numbers = [ batch.number for batch in selection.batches.values() if batch.selected and batch.scene == scene.number ]

            if batch_numbers:
                scenes[scene.number] = {
                    'batches' : batch_numbers,
                    'lines' : line_numbers,
                }

        if not scenes:
            raise ActionError(_("No scenes selected for translation"))

        command = StartTranslationCommand(self.datamodel, multithreaded=multithreaded, resume=False, scenes = scenes)

        self.QueueCommand(command)

    def ReparseSelection(self, selection : ProjectSelection):
        """
        Reparse selected batches
        """
        if not selection.AnyBatches():
            raise ActionError(_("Nothing selected to reparse"))

        self._validate_datamodel()

        batch_numbers = [ (batch.scene, batch.number) for batch in selection.selected_batches ]
        line_numbers = [ line.number for line in selection.selected_lines ]
        command = ReparseTranslationsCommand(batch_numbers, line_numbers)
        self.QueueCommand(command)

    def UpdateScene(self, scene_number : int, update : dict):
        """
        Update the user-updatable properties of a subtitle scene
        """
        logging.debug(f"Updating scene {scene_number} with {str(update)}")

        self._validate_datamodel()

        self.ExecuteCommandNow(EditSceneCommand(scene_number, update))

    def UpdateBatch(self, scene_number : int, batch_number : int, update : dict):
        """
        Update the user-updatable properties of a subtitle batch
        """
        logging.debug(f"Updating scene {scene_number} batch {batch_number} with {str(update)}")

        self._validate_datamodel()

        self.ExecuteCommandNow(EditBatchCommand(scene_number, batch_number, update))

    def UpdateLine(self, line_number : int, original_text : str|None, translated_text : str|None):
        """
        Update the user-updatable properties of a subtitle batch
        """
        logging.debug(f"Updating line {line_number} with {original_text or '<empty>'} > {translated_text or '<empty>'}")

        self._validate_datamodel()

        edit = {
            'text' : original_text,
            'translation' : translated_text,
        }

        self.ExecuteCommandNow(EditLineCommand(line_number, edit))

    def MergeSelection(self, selection : ProjectSelection):
        """
        Merge selected scenes, batches or lines
        """
        if not selection.Any():
            raise ActionError(_("Nothing selected to merge"))

        if not selection.IsContiguous():
            raise ActionError(_("Cannot merge non-sequential elements"))

        if selection.OnlyScenes():
            self.QueueCommand(MergeScenesCommand(selection.scene_numbers))

        elif selection.OnlyBatches():
            scene_number = selection.selected_batches[0].scene
            batch_numbers = [ batch.number for batch in selection.selected_batches ]
            self.QueueCommand(MergeBatchesCommand(scene_number, batch_numbers))

        elif selection.AnyLines():
            line_numbers = [ line.number for line in selection.selected_lines ]
            self.QueueCommand(MergeLinesCommand(line_numbers))

        else:
            raise ActionError(_("Unable to merge selection ({selection})").format(selection=str(selection)))

    def DeleteSelection(self, selection : ProjectSelection):
        """
        Delete scenes, batches or lines from the project
        """
        self._validate_datamodel()

        if not selection.Any():
            raise ActionError(_("Nothing selected to delete"))

        if not selection.AnyLines():
            raise ActionError(_("Cannot delete scenes or batches yet"))

        line_numbers = [ line.number for line in selection.selected_lines ]
        self.QueueCommand(DeleteLinesCommand(line_numbers))

    def SplitBatch(self, selection : ProjectSelection):
        """
        Split a batch in two at the specified index (optionally, using a different index for translated lines)
        """
        if not selection.Any():
            raise ActionError(_("Please select a line to split the batch at"))

        if selection.MultipleSelected():
            raise ActionError(_("Please select a single split point"))

        selected_line = selection.selected_lines[0]

        self._validate_datamodel()

        self.QueueCommand(SplitBatchCommand(selected_line.scene, selected_line.batch, selected_line.number))

    def SplitScene(self, selection : ProjectSelection):
        """
        Split a batch in two at the specified index (optionally, using a different index for translated lines)
        """
        if not selection.AnyBatches():
            raise ActionError(_("Please select a batch to split the scene at"))

        if selection.MultipleSelected():
            raise ActionError(_("Please select a single split point"))

        selected_batch = selection.selected_batches[0]

        self._validate_datamodel()

        self.QueueCommand(SplitSceneCommand(selected_batch.scene, selected_batch.number))

    def AutoSplitBatch(self, selection : ProjectSelection):
        """
        Split a batch in two automatically (using heuristics to find the best split point)
        """
        if not selection.AnyBatches() or selection.MultipleSelected():
            raise ActionError(_("Can only autosplit a single batch"))

        scene_number, batch_number = selection.selected_batches[0].key

        self.QueueCommand(AutoSplitBatchCommand(scene_number, batch_number))

    def _swap_text_and_translation(self, selection : ProjectSelection):
        """
        This is a simple action to test the GUI
        """
        if not selection.AnyBatches() or selection.MultipleSelected():
            raise ActionError(_("Can only swap text of a single batch"))

        scene_number, batch_number = selection.batch_numbers[0]

        self.QueueCommand(SwapTextAndTranslations(scene_number, batch_number))

    def _validate_datamodel(self):
        """
        Validate that there is a datamodel with subtitles that have been batched
        """
        if not self.datamodel or not self.datamodel.project:
            raise ActionError(_("Project is not valid"))

        if not self.datamodel.project.subtitles:
            raise ActionError(_("No subtitles"))

        if not self.datamodel.project.subtitles.scenes:
            raise ActionError(_("Subtitles have not been batched"))

    def _is_shift_pressed(self):
        return bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)

