from PySide6.QtWidgets import (QDialog, QFormLayout, QVBoxLayout, QLabel, QDialogButtonBox, QTabWidget, QWidget, )

from GuiSubtrans.ViewModel.BatchItem import BatchItem
from GuiSubtrans.ViewModel.LineItem import LineItem
from GuiSubtrans.ViewModel.SceneItem import SceneItem
from GuiSubtrans.Widgets.OptionsWidgets import CreateOptionWidget, MultilineTextOptionWidget, OptionWidget
from PySubtrans.Options import MULTILINE_OPTION
from PySubtrans.Helpers.Localization import _

class EditDialog(QDialog):
    def __init__(self, model, parent=None, title=None) -> None:
        super().__init__(parent)
        self.model = model
        self.editors = {}
        self.setMinimumWidth(800)

        self._layout : QVBoxLayout = QVBoxLayout(self)

        if title:
            self.setWindowTitle(title)
            self._layout.addWidget(QLabel(title))

        # Subclass populates the editor widget
        editor_widget = self.CreateEditor()

        self._layout.addWidget(editor_widget)

        self.buttonBox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)

        self._layout.addWidget(self.buttonBox)

    def GetFormLayout(self):
        layout = QFormLayout()
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        return layout

    def SetTabLayout(self, tab_widget : QTabWidget, layout, title : str):
        widget = QWidget()
        widget.setLayout(layout)
        tab_widget.addTab(widget, title)

    def AddDescription(self, form_layout : QFormLayout, description: str):
        """
        Add a description to the form layout
        """
        form_layout.addRow(QLabel(description))

    def AddMultilineEdit(self, form_layout : QFormLayout, key : str, read_only=False):
        """
        Add an editable field supporting multiline plaintext, optionally making it read-only
        """
        editor : OptionWidget = CreateOptionWidget(key, self.model.get(key), MULTILINE_OPTION)
        if read_only and isinstance(editor, MultilineTextOptionWidget):
            editor.SetReadOnly(True)

        form_layout.addRow(editor.key, editor)
        self.editors[key] = editor

    def UpdateModelFromEditor(self, key):
        """
        Update a field in the model with the value of the matching editor
        """
        self.model[key] = self.editors[key].GetValue()

    def CreateEditor(self):
        """
        Subclasses should override this method to add editable fields to the form layout
        """
        raise NotImplementedError

    def UpdateModel(self):
        """
        Subclasses should override this method to update the model from the form
        """
        raise NotImplementedError

    def accept(self):
        self.UpdateModel()
        return super().accept()

class EditSceneDialog(EditDialog):
    def __init__(self, item : SceneItem, parent=None) -> None:
        self.item = item
        super().__init__(item.scene_model, parent, title=_("Scene {num}").format(num=item.number))

    def CreateEditor(self) -> QWidget:
        form_layout = self.GetFormLayout()
        self.AddMultilineEdit(form_layout, 'summary')

        # Create widget, set layout, and return
        editor_widget = QWidget()
        editor_widget.setLayout(form_layout)
        return editor_widget

    def UpdateModel(self):
        self.UpdateModelFromEditor('summary')

class EditBatchDialog(EditDialog):
    def __init__(self, item : BatchItem, parent=None) -> None:
        self.item = item
        super().__init__(item.batch_model, parent, title=_("Scene {scene} Batch {batch}").format(scene=item.scene, batch=item.number))

    def CreateEditor(self):
        # Create tab widget
        tab_widget = QTabWidget()

        # Create "Summary" tab
        summary_layout = self.GetFormLayout()
        self.AddMultilineEdit(summary_layout, 'summary')
        self.SetTabLayout(tab_widget, summary_layout, _("Summary"))

        # Create "Prompt" tab if item has a prompt
        if self.item.prompt:
            prompt_layout = self.GetFormLayout()
            self.AddMultilineEdit(prompt_layout, 'prompt', read_only=True)
            self.SetTabLayout(tab_widget, prompt_layout, _("Prompt"))

        # Create "Response" tab if item has a response
        if self.item.response:
            response_layout = self.GetFormLayout()
            self.AddMultilineEdit(response_layout, 'response', read_only=True)
            if self.item.has_errors:
                self.AddMultilineEdit(response_layout, 'errors', read_only=True)

            self.SetTabLayout(tab_widget, response_layout, _("Response"))

            if self.item.reasoning:
                reasoning_layout = self.GetFormLayout()
                self.AddMultilineEdit(reasoning_layout, 'reasoning', read_only=True)
                self.SetTabLayout(tab_widget, reasoning_layout, _("Reasoning"))

        if self.item.debug_view:
            # Create debug tabs
            messages_layout = self.GetFormLayout()
            self.AddMultilineEdit(messages_layout, 'messages', read_only=True)
            self.SetTabLayout(tab_widget, messages_layout, _("Messages"))

            context_layout = self.GetFormLayout()
            self.AddMultilineEdit(context_layout, 'context', read_only=True)
            self.SetTabLayout(tab_widget, context_layout, _("Context"))

        return tab_widget

    def UpdateModel(self):
        self.UpdateModelFromEditor('summary')


class EditSubtitleDialog(EditDialog):
    def __init__(self, line : LineItem, parent=None) -> None:
        self.line = line
        self.model = {
            'original' : self.line.line_text if line else "",
            'translated'  : self.line.translation if line else "",
            'was_translated' : bool(self.line.translation)
        }
        super().__init__(self.model, parent, title=_("Line {line}: {start} --> {end}").format(line=self.line.number, start=self.line.start, end=self.line.end))

    def CreateEditor(self) -> QWidget:
        form_layout = self.GetFormLayout()
        self.AddMultilineEdit(form_layout, 'original')
        self.AddMultilineEdit(form_layout, 'translated')

        editor_widget = QWidget()
        editor_widget.setLayout(form_layout)
        return editor_widget

    def UpdateModel(self):
        self.UpdateModelFromEditor('original')
        self.UpdateModelFromEditor('translated')
