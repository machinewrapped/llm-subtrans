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
    QSizePolicy
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

        self.form_layout = QFormLayout()
        self.prompt_edit = self._add_form_option("prompt", self.instructions.prompt, str, _("Prompt for each translation request"))
        self.task_type_edit = self._add_form_option("task_type", self.instructions.task_type, str, _("Type of response expected for each line (must match the example format)"))
        self.instructions_edit = self._add_form_option("instructions", self.instructions.instructions, MULTILINE_OPTION, _("System instructions for the translator"))
        self.retry_instructions_edit = self._add_form_option("retry_instructions", self.instructions.retry_instructions, MULTILINE_OPTION, _("Supplementary instructions when retrying"))
        self.form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.button_layout = QHBoxLayout()

        self.select_file = self._create_instruction_dropdown(self._select_instructions)
        self.load_button = self._create_button(_("Load Instructions"), self._load_instructions)
        self.save_button = self._create_button(_("Save Instructions"), self._save_instructions)
        self.default_button = self._create_button(_("Defaults"), self.set_defaults)
        self.ok_button = self._create_button(_("OK"), self.accept)
        self.cancel_button = self._create_button(_("Cancel"), self.reject)

        layout = QVBoxLayout()
        layout.addLayout(self.form_layout)
        layout.addLayout(self.button_layout)

        self.setLayout(layout)

    def _add_form_option(self, key, initial_value, key_type, tooltip = None):
        if initial_value:
            initial_value = initial_value.replace('\r\n', '\n')

        input = CreateOptionWidget(key, initial_value, key_type, tooltip)
        input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.form_layout.addRow(key, input)
        return input

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
