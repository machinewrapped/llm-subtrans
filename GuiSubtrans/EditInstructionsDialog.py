import logging
from PySide6.QtWidgets import (
    QStyle,
    QApplication,
    QFormLayout,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QFileDialog,
    QSizePolicy,
    QTabWidget,
    QWidget
    )
from GuiSubtrans.Widgets.OptionsWidgets import CreateOptionWidget

from PySubtrans.Options import MULTILINE_OPTION, Options
from PySubtrans.Instructions import Instructions
from PySubtrans.Helpers.InstructionsHelpers import GetInstructionsFiles, GetInstructionsUserPath, LoadInstructions, LoadInstructionsFile, SaveInstructions
from PySubtrans.Helpers.Localization import _

class EditInstructionsDialog(QDialog):
    def __init__(self, settings : dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Edit Instructions"))
        self.setMinimumWidth(800)

        self.instructions : Instructions = Instructions(settings)
        self.target_language = None
        self.filters = _("Text Files (*.txt);;All Files (*))")

        # Top fields always visible
        top_form = QFormLayout()
        top_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.prompt_edit = self._create_option("prompt", self.instructions.prompt, str, _("Prompt for each translation request"))
        top_form.addRow(self.prompt_edit.name, self.prompt_edit)
        self.task_type_edit = self._create_option("task_type", self.instructions.task_type, str, _("Type of response expected for each line (must match the example format)"))
        top_form.addRow(self.task_type_edit.name, self.task_type_edit)

        # Tabbed sections for the four instruction areas
        self.tab_widget = QTabWidget()
        self.instructions_edit = self._add_tab(_("Instructions"), "instructions", self.instructions.instructions, _("System instructions for the translator"))
        self.retry_instructions_edit = self._add_tab(_("Retry"), "retry_instructions", self.instructions.retry_instructions, _("Supplementary instructions when retrying"))
        self.terminology_instructions_edit = self._add_tab(_("Terminology"), "terminology_instructions", self.instructions.terminology_instructions, _("Instructions for building a terminology list"))
        self.speaker_instructions_edit = self._add_tab(_("Speakers"), "speaker_instructions", self.instructions.speaker_instructions, _("Instructions for translating speaker-labelled lines"))

        # Button bar
        self.button_layout = QHBoxLayout()
        self.select_file = self._create_instruction_dropdown(self._select_instructions)
        self.load_button = self._create_button(_("Load Instructions"), self._load_instructions)
        self.save_button = self._create_button(_("Save Instructions"), self._save_instructions)
        self.default_button = self._create_button(_("Defaults"), self.set_defaults)
        self.ok_button = self._create_button(_("OK"), self.accept)
        self.cancel_button = self._create_button(_("Cancel"), self.reject)

        layout = QVBoxLayout()
        layout.addLayout(top_form)
        layout.addWidget(self.tab_widget)
        layout.addLayout(self.button_layout)

        self.setLayout(layout)

    def _create_option(self, key, initial_value, key_type, tooltip=None):
        """Create an option widget without adding it to any layout."""
        if initial_value:
            initial_value = initial_value.replace('\r\n', '\n')

        widget = CreateOptionWidget(key, initial_value, key_type, tooltip)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        return widget

    def _add_tab(self, tab_title : str, key : str, initial_value, tooltip=None):
        """Create a multiline option widget and add it as a tab."""
        widget = self._create_option(key, initial_value, MULTILINE_OPTION, tooltip)
        tab_form = QFormLayout()
        tab_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        tab_form.addRow(widget)
        container = QWidget()
        container.setLayout(tab_form)
        self.tab_widget.addTab(container, tab_title)
        return widget

    def _create_instruction_dropdown(self, on_change):
        instructions_files = GetInstructionsFiles()
        initial_value = self.instructions.instruction_file
        dropdown = CreateOptionWidget('instruction_file', initial_value, instructions_files)
        dropdown.contentChanged.connect(on_change)
        self.button_layout.addWidget(dropdown)
        return dropdown

    def _create_button(self, text, on_click):
        button = QPushButton(text)
        button.clicked.connect(on_click)
        self.button_layout.addWidget(button)
        return button

    def accept(self):
        if self._check_for_edited_instructions():
            self.instructions.prompt = self.prompt_edit.GetValue()
            self.instructions.task_type = self.task_type_edit.GetValue()
            self.instructions.instructions = self.instructions_edit.GetValue()
            self.instructions.retry_instructions = self.retry_instructions_edit.GetValue()
            self.instructions.terminology_instructions = self.terminology_instructions_edit.GetValue()
            self.instructions.speaker_instructions = self.speaker_instructions_edit.GetValue()
            self.instructions.instruction_file = None

        # Check that {task_type} is found in instructions
        task_type = self.instructions.task_type
        instructions = self.instructions.instructions
        if task_type is None or not isinstance(task_type, str) or not task_type.strip():
            logging.error(f"Task type cannot be empty. Please check the task type.")
        elif not instructions or task_type not in instructions:
            logging.error(f"Task type '{task_type}' not found in instructions. Please check the instructions.")

        super().accept()

    def reject(self):
        super().reject()

    def _check_for_edited_instructions(self):
        '''Check if the instructions have been edited'''
        if self.prompt_edit.GetValue() != self.instructions.prompt:
            return True
        if self.task_type_edit.GetValue() != self.instructions.task_type:
            return True
        if self.instructions_edit.GetValue() != self.instructions.instructions:
            return True
        if self.retry_instructions_edit.GetValue() != self.instructions.retry_instructions:
            return True
        if self.terminology_instructions_edit.GetValue() != self.instructions.terminology_instructions:
            return True
        if self.speaker_instructions_edit.GetValue() != self.instructions.speaker_instructions:
            return True

        return False

    @property
    def load_icon(self):
        return QApplication.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton)

    @property
    def save_icon(self):
        return QApplication.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)

    def _select_instructions(self):
        '''Select an instruction file from the dropdown'''
        instructions_name = self.select_file.GetValue()

        try:
            self.instructions = LoadInstructions(instructions_name)

            self.prompt_edit.SetValue(self.instructions.prompt)
            self.task_type_edit.SetValue(self.instructions.task_type)
            self.instructions_edit.SetValue(self.instructions.instructions)
            self.retry_instructions_edit.SetValue(self.instructions.retry_instructions)
            self.terminology_instructions_edit.SetValue(self.instructions.terminology_instructions)
            self.speaker_instructions_edit.SetValue(self.instructions.speaker_instructions)

        except Exception as e:
            logging.error(f"Unable to load instructions: {str(e)}")

    def _load_instructions(self):
        '''Load instructions from a file'''
        path = GetInstructionsUserPath(self.instructions.instruction_file)
        file_name, dummy = QFileDialog.getOpenFileName(self, _("Load Instructions"), dir=path, filter=self.filters) # type: ignore[ignore-unused]
        if file_name:
            try:
                self.instructions = LoadInstructionsFile(file_name)

                self.prompt_edit.SetValue(self.instructions.prompt)
                self.task_type_edit.SetValue(self.instructions.task_type)
                self.instructions_edit.SetValue(self.instructions.instructions)
                self.retry_instructions_edit.SetValue(self.instructions.retry_instructions)
                self.terminology_instructions_edit.SetValue(self.instructions.terminology_instructions)
                self.speaker_instructions_edit.SetValue(self.instructions.speaker_instructions)

            except Exception as e:
                logging.error(f"Unable to read instruction file: {str(e)}")

    def _save_instructions(self):
        '''Save instructions to a file'''
        filepath = GetInstructionsUserPath(self.instructions.instruction_file)
        file_name, dummy = QFileDialog.getSaveFileName(self, _("Save Instructions"), dir=filepath, filter=self.filters) # type: ignore[ignore-unused]
        if file_name:
            try:
                self.instructions.prompt = self.prompt_edit.GetValue()
                self.instructions.task_type = self.task_type_edit.GetValue()
                self.instructions.instructions = self.instructions_edit.GetValue()
                self.instructions.retry_instructions = self.retry_instructions_edit.GetValue()
                self.instructions.terminology_instructions = self.terminology_instructions_edit.GetValue()
                self.instructions.speaker_instructions = self.speaker_instructions_edit.GetValue()

                SaveInstructions(self.instructions, file_name)

            except Exception as e:
                logging.error(f"Unable to write instruction file: {str(e)}")

    def set_defaults(self):
        options = Options()
        instructions = options.GetInstructions()
        self.prompt_edit.SetValue(instructions.prompt)
        self.task_type_edit.SetValue(instructions.task_type)
        self.instructions_edit.SetValue(instructions.instructions)
        self.retry_instructions_edit.SetValue(instructions.retry_instructions)
        self.terminology_instructions_edit.SetValue(instructions.terminology_instructions)
        self.speaker_instructions_edit.SetValue(instructions.speaker_instructions)
