from copy import deepcopy
import logging
import os
from typing import cast

from PySide6.QtCore import Qt, QThread, Signal, Slot, QRecursiveMutex, QMutexLocker
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QDialogButtonBox, QFormLayout, QFrame, QLabel, QWidget, QLayout)

from GuiSubtrans.ProjectDataModel import ProjectDataModel
from GuiSubtrans.Widgets.OptionsWidgets import CreateOptionWidget, DropdownOptionWidget, OptionWidget

from PySubtrans.Helpers.InstructionsHelpers import GetInstructionsFiles, LoadInstructions
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleBatcher import SubtitleBatcher
from PySubtrans.SubtitleLine import SubtitleLine
from PySubtrans.SubtitleProcessor import SubtitleProcessor
from PySubtrans.SubtitleProject import SubtitleProject
from PySubtrans.SubtitleScene import SubtitleScene
from PySubtrans.Helpers.Localization import _
from PySubtrans.SubtitleFormatRegistry import SubtitleFormatRegistry

if os.environ.get("DEBUG_MODE") == "1":
    try:
        import debugpy # type: ignore
    except ImportError:
        pass

class NewProjectSettings(QDialog):
    OPTIONS = {
        'target_language': (str, _("Language to translate the subtitles to")),
        'provider': ([], _("The AI translation service to use")),
        'model': (str, _("AI model to use as the translator")),
        'scene_threshold': (float, _("Number of seconds gap to consider it a new scene")),
        'min_batch_size': (int, _("Fewest lines to send in separate batch")),
        'max_batch_size': (int, _("Most lines to send in each batch")),
        'preprocess_subtitles': (bool, _("Preprocess subtitles before batching")),
        'instruction_file': (str, _("Detailed instructions for the translator")),
        'prompt': (str, _("High-level instructions for the translator")),
        'format': (str, _("Output subtitle format"))
    }

    def __init__(self, datamodel : ProjectDataModel, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Project Settings"))
        self.setMinimumWidth(800)

        self.fields = {}

        self.datamodel = datamodel
        self.project : SubtitleProject|None = datamodel.project
        self.settings = datamodel.project_options.GetSettings()

        self.providers = datamodel.available_providers
        self.OPTIONS['provider'] = (self.providers, self.OPTIONS['provider'][1])
        self.settings['provider'] = datamodel.provider

        available_models = datamodel.available_models
        self.OPTIONS['model'] = (available_models, self.OPTIONS['model'][1])
        self.settings['model'] = datamodel.selected_model

        if self.project and self.project.subtitles:
            formats = SubtitleFormatRegistry.enumerate_formats()
            self.OPTIONS['format'] = (formats, _("Output subtitle format"))
            self.settings['format'] = self.project.subtitles.file_format

        instruction_files = GetInstructionsFiles()
        if instruction_files:
            self.OPTIONS['instruction_file'] = (instruction_files, self.OPTIONS['instruction_file'][1])

        settings_widget = QFrame(self)

        self.form_layout = QFormLayout(settings_widget)
        self.form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        for key, setting in self.OPTIONS.items():
            key_type, tooltip = setting
            try:
                field = CreateOptionWidget(key, self.settings[key], key_type, tooltip=tooltip)
                field.contentChanged.connect(lambda setting=field: self._on_setting_changed(setting.key, setting.GetValue()), type=Qt.ConnectionType.QueuedConnection)
                self.form_layout.addRow(field.name, field)
                self.fields[key] = field

            except Exception as e:
                logging.error(_("Unable to create option widget for {key}: {error}").format(key=key, error=e))

        self._layout = QVBoxLayout(self) # type: ignore
        self._add_widget(settings_widget)

        self.preview_widget = QLabel(self)
        self._add_widget(self.preview_widget)

        self.buttonBox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok, self)
        self.buttonBox.accepted.connect(self.accept, type=Qt.ConnectionType.QueuedConnection)
        self._add_widget(self.buttonBox)

        self.fields['instruction_file'].contentChanged.connect(self._update_instruction_file, type=Qt.ConnectionType.QueuedConnection)

        self.preview_threads = []
        self.preview_count = 0
        self.preview_mutex = QRecursiveMutex()

        self._preview_batches()

    def _add_widget(self, settings_widget):
        self._layout.addWidget(settings_widget) # type: ignore

    def accept(self):
        try:
            self._update_settings()

            instructions_file = self.settings.get('instruction_file')
            if instructions_file and isinstance(instructions_file, str):
                logging.info(_("Project instructions set from {file}").format(file=instructions_file))
                try:
                    instructions = LoadInstructions(instructions_file)

                    self.settings['prompt'] = instructions.prompt
                    self.settings['instructions'] = instructions.instructions
                    self.settings['retry_instructions'] = instructions.retry_instructions
                    self.settings['task_type'] = instructions.task_type
                    if instructions.target_language:
                        self.settings['target_language'] = instructions.target_language

                    logging.debug(_("Prompt: {text}").format(text=instructions.prompt))
                    logging.debug(_("Instructions: {text}").format(text=instructions.instructions))

                except Exception as e:
                    logging.error(_("Unable to load instructions from {file}: {error}").format(file=instructions_file, error=e))

        except Exception as e:
            logging.error(_("Unable to update settings: {error}").format(error=e))

        # Wait for any remaining preview threads to complete
        self._wait_for_threads()

        super().accept()

    def _on_setting_changed(self, key, value):
        if key == 'provider':
            self._update_provider_settings(value)
        else:
            self.settings[key] = value
            if value is not None:
                self._preview_batches()

    def _update_provider_settings(self, provider : str):
        try:
            self.datamodel.UpdateProjectSettings({ "provider": provider})
            model_options : DropdownOptionWidget = self.fields['model']
            model_options.SetOptions(self.datamodel.available_models, self.datamodel.selected_model)
            self.settings['provider'] = provider
            self.settings['model'] = self.datamodel.selected_model
        except Exception as e:
            logging.error(_("Provider error: {error}").format(error=e))

    def _update_settings(self):
        layout : QFormLayout = cast(QFormLayout, self.form_layout.layout())

        for row in range(layout.rowCount()): # type: ignore
            field : OptionWidget = cast(OptionWidget, layout.itemAt(row, QFormLayout.ItemRole.FieldRole).widget())
            self.settings[field.key] = field.GetValue()

    def _update_instruction_file(self):
        """ Update the prompt when the instruction file is changed """
        instruction_file = self.fields['instruction_file'].GetValue()
        if instruction_file:
            try:
                instructions = LoadInstructions(instruction_file)
                self.fields['prompt'].SetValue(instructions.prompt)
                if instructions.target_language:
                    self.fields['target_language'].SetValue(instructions.target_language)
            except Exception as e:
                logging.error(_("Unable to load instructions from {file}: {error}").format(file=instruction_file, error=e))

    def _preview_batches(self):
        try:
            self._update_settings()

            if self.project and self.project.subtitles and self.project.subtitles.originals:
                with QMutexLocker(self.preview_mutex):
                    self.preview_count += 1
                    preview_thread = BatchPreviewWorker(self.preview_count, self.settings, self.project.subtitles.originals)
                    preview_thread.update_preview.connect(self._update_preview_widget, type=Qt.ConnectionType.QueuedConnection)
                    preview_thread.finished.connect(self._remove_preview_thread, type=Qt.ConnectionType.QueuedConnection)
                    self.preview_threads.append(preview_thread)
                    preview_thread.start()

        except Exception as e:
            logging.error(_("Unable to preview batches: {error}").format(error=e))

    @Slot(int, str)
    def _update_preview_widget(self, count : int, text : str):
        with QMutexLocker(self.preview_mutex):
            if count == self.preview_count:
                self.preview_widget.setText(text)

    @Slot()
    def _remove_preview_thread(self):
        with QMutexLocker(self.preview_mutex):
            thread = self.sender()
            if thread:
                self.preview_threads = [x for x in self.preview_threads if x != thread]
                thread.deleteLater()

    def _wait_for_threads(self):
        if self.preview_threads:
            QThread.msleep(500)
            with QMutexLocker(self.preview_mutex):
                for thread in self.preview_threads:
                    thread.update_preview.disconnect(self._update_preview_widget)
                    thread.finished.disconnect(self._remove_preview_thread)
                    thread.quit()
                    thread.wait()
                self.preview_threads = []

class BatchPreviewWorker(QThread):
    update_preview = Signal(int, str)

    def __init__(self, count : int, settings : SettingsType, subtitles : list[SubtitleLine], parent=None):
        super().__init__(parent)
        self.count : int = count
        self.settings : SettingsType = deepcopy(settings)
        self.subtitles : list[SubtitleLine] = deepcopy(subtitles)

    def run(self):
        if 'debugpy' in globals():
            debugpy.debug_this_thread()  # type: ignore

        try:
            if self.settings.get('preprocess_subtitles'):
                preprocessor = SubtitleProcessor(self.settings)
                lines = preprocessor.PreprocessSubtitles(self.subtitles)
            else:
                lines = self.subtitles

            batcher : SubtitleBatcher = SubtitleBatcher(self.settings)
            if batcher.max_batch_size < batcher.min_batch_size:
                self.update_preview.emit(self.count, _("Max batch size is less than min batch size"))
                return

            scenes : list[SubtitleScene] = batcher.BatchSubtitles(lines)
            batch_count = sum(scene.size for scene in scenes)
            line_count = sum(scene.linecount for scene in scenes)

            preview_text = _("{lines} lines in {scenes} scenes and {batches} batches").format(lines=line_count, scenes=len(scenes), batches=batch_count)
            self.update_preview.emit(self.count, preview_text)

        except Exception as e:
            self.update_preview.emit(self.count, _("Error: {error}").format(error=e))