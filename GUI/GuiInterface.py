import logging
import os

from PySide6.QtCore import Qt, QObject, Signal, QTimer, QMutexLocker
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QDialog,
    QMessageBox
)

from GUI.AboutDialog import AboutDialog
from GUI.Command import Command
from GUI.CommandQueue import CommandQueue
from GUI.Commands.BatchSubtitlesCommand import BatchSubtitlesCommand
from GUI.Commands.LoadSubtitleFile import LoadSubtitleFile
from GUI.Commands.SaveProjectFile import SaveProjectFile
from GUI.Commands.SaveTranslationFile import SaveTranslationFile
from GUI.FirstRunOptions import FirstRunOptions
from GUI.GUICommands import ExitProgramCommand
from GUI.GuiHelpers import LoadStylesheet
from GUI.NewProjectSettings import NewProjectSettings
from GUI.ProjectActions import ProjectActions
from GUI.ProjectDataModel import ProjectDataModel
from GUI.SettingsDialog import SettingsDialog
from PySubtitle.Options import Options
from PySubtitle.SettingsType import SettingsType
from PySubtitle.SubtitleError import ProviderConfigurationError, SubtitleError
from PySubtitle.TranslationProvider import TranslationProvider
from PySubtitle.VersionCheck import CheckIfUpdateAvailable, CheckIfUpdateCheckIsRequired
from PySubtitle.version import __version__
from PySubtitle.Helpers.Localization import _, set_language

class GuiInterface(QObject):
    """
    Interface to interact with the GUI
    """
    dataModelChanged = Signal(object)
    settingsChanged = Signal(dict)
    uiLanguageChanged = Signal(str)
    commandAdded = Signal(object)
    commandStarted = Signal(object)
    commandComplete = Signal(object)
    commandUndone = Signal(object)
    prepareForSave = Signal()
    projectSaved = Signal()
    showProjectSettings = Signal(bool)

    def __init__(self, mainwindow : QMainWindow, options : Options):
        super().__init__()

        self.mainwindow = mainwindow

        if not options:
            options = Options()
            options.InitialiseInstructions()
            options.LoadSettings()

        options.add('available_providers', sorted(TranslationProvider.get_providers()))

        self.global_options : Options = options

        # Create the project data model
        self.datamodel : ProjectDataModel = ProjectDataModel(options=options)

        # Create the command queue
        self.command_queue = CommandQueue(mainwindow)
        self.command_queue.SetMaxThreadCount(options.get('max_threads', 1))
        self.command_queue.commandStarted.connect(self._on_command_started, Qt.ConnectionType.QueuedConnection)
        self.command_queue.commandExecuted.connect(self._on_command_complete, Qt.ConnectionType.QueuedConnection)
        self.command_queue.commandAdded.connect(self._on_command_added, Qt.ConnectionType.QueuedConnection)
        self.command_queue.commandUndone.connect(self._on_command_undone, Qt.ConnectionType.QueuedConnection)

        # Create centralised action handler
        self.action_handler = ProjectActions(command_queue=self.command_queue, datamodel=self.datamodel, mainwindow=self.mainwindow)
        self.action_handler.actionError.connect(self._on_error)
        self.action_handler.showSettings.connect(self.ShowSettingsDialog)
        self.action_handler.showProviderSettings.connect(self.ShowProviderSettingsDialog)
        self.action_handler.showProjectSettings.connect(self.showProjectSettings)
        self.action_handler.saveSettings.connect(self.SaveSettings)
        self.action_handler.loadProject.connect(self.LoadProject)
        self.action_handler.saveProject.connect(self.SaveProject)
        self.action_handler.showAboutDialog.connect(self.ShowAboutDialog)
        self.action_handler.exitProgram.connect(self._exit_program)

        # Autosave timer - triggers 20 seconds after last change
        self._autosave_timer = QTimer()
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.timeout.connect(self._perform_autosave)
        
        if self.global_options.get('last_used_path'):
            self.action_handler.last_used_path = self.global_options.get_str('last_used_path')

    def GetMainWindow(self) -> QMainWindow:
        """
        Get a reference to the application main window
        """
        return self.mainwindow

    def QueueCommand(self, command : Command, callback = None, undo_callback = None):
        """
        Add a command to the command queue and set the datamodel
        """
        self.command_queue.AddCommand(command, self.datamodel, callback=callback, undo_callback=undo_callback)

    def GetCommandQueue(self):
        """
        Get the command queue
        """
        return self.command_queue

    def GetDataModel(self):
        """
        Get the data model
        """
        return self.datamodel

    def SetDataModel(self, datamodel : ProjectDataModel):
        """
        Set the data model
        """
        self.datamodel = datamodel
        self.action_handler.SetDataModel(datamodel)
        self.dataModelChanged.emit(datamodel)

    def GetActionHandler(self):
        """
        Get the action handler
        """
        return self.action_handler

    def ShowSettingsDialog(self):
        """
        Open user settings dialog and update options
        """
        provider_cache = self.datamodel.provider_cache if self.datamodel else None
        dialog = SettingsDialog(self.global_options, provider_cache=provider_cache, parent=self.GetMainWindow())
        result = dialog.exec()

        if result == QDialog.DialogCode.Accepted:
            self.UpdateSettings(dialog.settings)

            logging.info("Settings updated")

    def ShowProviderSettingsDialog(self):
        """
        Open the settings dialog with the provider settings focused
        """
        provider_cache = self.datamodel.provider_cache if self.datamodel else None
        dialog = SettingsDialog(self.global_options, provider_cache=provider_cache, parent=self.GetMainWindow(), focus_provider_settings=True)
        result = dialog.exec()
        if result == QDialog.DialogCode.Accepted:
            self.UpdateSettings(dialog.settings)

    def SaveSettings(self):
        """
        Save the global settings
        """
        self.prepareForSave.emit()
        self.global_options.SaveSettings()

    def UpdateSettings(self, settings : SettingsType):
        """
        Update the global settings and project settings, and save if required
        """
        updated_settings : SettingsType = SettingsType({
                k: v for k, v in settings.items() if v != self.global_options.get(k)
            })

        if not updated_settings:
            return

        # Update and save global settings
        self.global_options.update(updated_settings)
        self.global_options.SaveSettings()

        # Update the project and provider settings
        self.datamodel.UpdateSettings(updated_settings)

        if not self.datamodel.ValidateProviderSettings():
            logging.warning(_("Translation provider settings are not valid. Please check the settings."))

        # If UI language changed, reinitialize i18n and refresh visible UI
        if 'ui_language' in updated_settings:
            ui_language : str = updated_settings.get_str('ui_language') or 'en'
            self.UpdateUiLanguage(ui_language)

        self.settingsChanged.emit(updated_settings)

        if 'theme' in updated_settings:
            LoadStylesheet(self.global_options.theme)

    def UpdateUiLanguage(self, language_code: str):
        """Apply a new UI language at runtime and refresh visible UI elements."""
        try:
            set_language(language_code)

            self.uiLanguageChanged.emit(language_code)

        except Exception as e:
            logging.warning(_("Failed to switch language - restart the application: {error}").format(error=e))

    def UpdateProjectSettings(self, settings : dict):
        """
        Update the project settings
        """
        if settings:
            self.datamodel.UpdateProjectSettings(settings)
            self.settingsChanged.emit(settings)

    def Startup(self, filepath : str|None = None):
        """
        Perform startup tasks
        """
        options = self.global_options

        LoadStylesheet(options.theme)

        if options.provider is None or options.get('firstrun'):
            # Configure critical settings
            self._first_run(options)
        else:
            # Check if the translation provider is configured correctly
            self._check_provider_settings(options)

            if filepath:
                # Load file if we were opened with one
                filepath = os.path.abspath(filepath)
                self.LoadProject(filepath)

        logging.info(f"GUI-Subtrans {__version__}")

        # Check if there is a more recent version on Github (TODO: make this optional)
        if CheckIfUpdateCheckIsRequired():
            CheckIfUpdateAvailable()

    def _check_provider_settings(self, options : Options):
        self.action_handler.CheckProviderSettings(options)

    def PrepareToExit(self):
        """
        Clear the command queue and exit the program
        """
        if self.command_queue:
            self.command_queue.Stop()

        if self.datamodel and self.datamodel.project:
            self.datamodel.project.SaveProject()

    def LoadProject(self, filepath : str, reload_subtitles : bool = False):
        """
        Load a project file
        """
        command = LoadSubtitleFile(filepath, self.global_options, reload_subtitles=reload_subtitles)
        self.QueueCommand(command, callback=self._on_project_loaded)

    def SaveProject(self, filepath : str|None = None):
        """
        Save the project file
        """
        if not self.datamodel or not self.datamodel.project:
            raise SubtitleError(_("No project data"))

        #TODO: consolidate SaveProjectFile and SaveTranslationFile into a single SaveProject command
        if self.datamodel.use_project_file:
            command = SaveProjectFile(self.datamodel.project, filepath)
        else:
            command = SaveTranslationFile(self.datamodel.project, filepath)

        self.QueueCommand(command, callback=self._on_save)

    def ShowNewProjectSettings(self, datamodel : ProjectDataModel):
        """
        Show the new project settings dialog
        """
        if not datamodel.project:
            logging.error(_("No project data"))
            return

        try:
            dialog = NewProjectSettings(datamodel, parent=self.GetMainWindow())

            if dialog.exec() == QDialog.DialogCode.Accepted:
                datamodel.UpdateProjectSettings(dialog.settings)
                self._check_provider_settings(datamodel.project_options)
                self.QueueCommand(BatchSubtitlesCommand(datamodel.project, datamodel.project_options))
                logging.info("Project settings set")

        except Exception as e:
            logging.error(f"Error initialising project settings: {str(e)}")

    def ShowAboutDialog(self):
        """
        Show the about dialog
        """
        _ = AboutDialog(parent=self.GetMainWindow()).exec()

    def _on_command_added(self, command : Command):
        """
        Handle the addition of a command to the queue
        """
        logging.debug(f"Added a {type(command).__name__} command to the queue")
        self.commandAdded.emit(command)

    def _on_command_started(self, command : Command):
        """
        Handle the start of a command
        """
        logging.debug(f"{type(command).__name__} command started")
        self.commandStarted.emit(command)

    def _on_command_undone(self, command : Command):
        """
        Handle the undoing of a command
        """
        logging.debug(f"{type(command).__name__} command undone")
        for model_update in command.model_updates:
            self.datamodel.UpdateViewModel(model_update)

        command.ClearModelUpdates()

        self.commandUndone.emit(command)

    def _on_command_complete(self, command : Command):
        """
        Handle the completion of a command
        """
        if isinstance(command, ExitProgramCommand):
            app = QApplication.instance()
            if app:
                app.quit()
            return

        logging.debug(f"A {type(command).__name__} command {'succeeded' if command.succeeded else 'failed'}")

        if command.succeeded:
            if command.model_updates:
                for model_update in command.model_updates:
                    self.datamodel.UpdateViewModel(model_update)

                command.ClearModelUpdates()

            elif command.datamodel and command.datamodel != self.datamodel:
                # Shouldn't need to do a full model rebuild often?
                self.SetDataModel(command.datamodel)

            elif command.datamodel is None:
                self.dataModelChanged.emit(None)

        # Schedule autosave if the command queue is empty and the project has changed
        if not self.command_queue.has_commands:
            if self.datamodel and self.datamodel.autosave_enabled and self.datamodel.project and self.datamodel.project.needs_writing:
                self._autosave_timer.start(20000)

        self.commandComplete.emit(command)

    def _perform_autosave(self):
        """
        Perform autosave if conditions are met
        """
        if self.datamodel:
            with QMutexLocker(self.datamodel.mutex):
                if self.datamodel.autosave_enabled and self.datamodel.project and self.datamodel.project.needs_writing:
                    self.SaveProject()

    def _on_project_loaded(self, command : LoadSubtitleFile):
        """
        Update the data model and last used path after loading a project
        """
        if command.datamodel is None:
            logging.error(_("Failed to load project data model."))
            return

        self.SetDataModel(command.datamodel)
        self._update_last_used_path(command.filepath)
        if self.datamodel.is_project_valid and not self.datamodel.is_project_initialised:
            self.ShowNewProjectSettings(self.datamodel)

    def _on_save(self, command : SaveProjectFile|SaveTranslationFile):
        """
        Update the data model and last used path after saving the project
        """
        if command.datamodel and command.filepath:
            self._update_last_used_path(command.filepath)
            if command.datamodel != self.datamodel:
                self.SetDataModel(command.datamodel)

        self.projectSaved.emit()

    def _update_last_used_path(self, filepath : str):
        """
        Update the last used path in the global options
        """
        self.action_handler.last_used_path = self.global_options.get_str('last_used_path')
        self.global_options.add('last_used_path', os.path.dirname(filepath))
        self.global_options.SaveSettings()

    def _first_run(self, options: Options):
        """
        First run initialisation
        """
        if not options.available_providers:
            logging.error(_("No translation providers available. Please install one or more providers."))
            QMessageBox.critical(self.mainwindow, _("Error"), _("No translation providers available. Please install one or more providers."))
            self.QueueCommand(ExitProgramCommand())
            return

        first_run_options = FirstRunOptions(options, parent = self.GetMainWindow())
        result = first_run_options.exec()

        if result == QDialog.DialogCode.Accepted:
            logging.info("First run options set")
            initial_settings = first_run_options.GetSettings()
            self.UpdateSettings(initial_settings)

            self._check_provider_settings(self.global_options)

    def _on_error(self, error : object):
        """
        Handle an error from the action handler
        """
        logging.error(str(error))

        if isinstance(error, ProviderConfigurationError):
            if self.datamodel and self.datamodel.project_options:
                logging.warning(_("Please configure the translation provider settings"))
                self.ShowProviderSettingsDialog()

    def _exit_program(self):
        self.PrepareToExit()
        self.QueueCommand(ExitProgramCommand())
