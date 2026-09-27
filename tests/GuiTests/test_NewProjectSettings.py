"""Verify the new project settings dialog applies a preferred instruction file."""
from tests.GuiTestSupport import ConfigureOffscreenPlatform

ConfigureOffscreenPlatform()

from PySide6.QtWidgets import QApplication

from GuiSubtrans.NewProjectSettings import NewProjectSettings
from PySubtrans.Helpers.InstructionsHelpers import DEFAULT_INSTRUCTIONS_FILE, TRANSCRIBED_INSTRUCTIONS_FILE, LoadInstructions
from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Options import Options
from tests.GuiTests.DataModelHelpers import CreateTestDataModel
from tests.TestData.chinese_dinner import chinese_dinner_data


class TestNewProjectSettingsInstructions(LoggedTestCase):
    """A preferred instruction file replaces the default instructions but not a deliberate choice."""

    application : QApplication

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        existing = QApplication.instance()
        cls.application = existing if isinstance(existing, QApplication) else QApplication([])

    def _make_dialog(self, instruction_file : str, preferred : str|None) -> NewProjectSettings:
        """Create the dialog for a project using the given instruction file."""
        options = Options({'instruction_file': instruction_file})
        datamodel = CreateTestDataModel(chinese_dinner_data, options)
        dialog = NewProjectSettings(datamodel, preferred_instruction_file=preferred)
        self.addCleanup(self._dispose, dialog)
        return dialog

    def _dispose(self, dialog : NewProjectSettings) -> None:
        dialog._wait_for_threads()
        dialog.deleteLater()
        self.application.processEvents()

    def test_preferred_file_replaces_default_instructions(self) -> None:
        """A project on the default instructions switches to the preferred file and its prompt."""
        dialog = self._make_dialog(DEFAULT_INSTRUCTIONS_FILE, TRANSCRIBED_INSTRUCTIONS_FILE)

        expected_prompt = LoadInstructions(TRANSCRIBED_INSTRUCTIONS_FILE).prompt
        self.assertLoggedEqual('selected instruction file', TRANSCRIBED_INSTRUCTIONS_FILE, dialog.fields['instruction_file'].GetValue())
        self.assertLoggedEqual('prompt from preferred file', expected_prompt, dialog.fields['prompt'].GetValue())

    def test_explicit_choice_is_kept(self) -> None:
        """A project that chose non-default instructions keeps them."""
        chosen = "instructions (brief).txt"
        dialog = self._make_dialog(chosen, TRANSCRIBED_INSTRUCTIONS_FILE)

        self.assertLoggedEqual('instruction file unchanged', chosen, dialog.fields['instruction_file'].GetValue())

    def test_unavailable_preference_is_ignored(self) -> None:
        """A preferred file that is not installed leaves the default selected."""
        dialog = self._make_dialog(DEFAULT_INSTRUCTIONS_FILE, "instructions (does not exist).txt")

        self.assertLoggedEqual('instruction file unchanged', DEFAULT_INSTRUCTIONS_FILE, dialog.fields['instruction_file'].GetValue())

    def test_no_preference_keeps_default(self) -> None:
        """Without a preference the dialog shows the project's instructions."""
        dialog = self._make_dialog(DEFAULT_INSTRUCTIONS_FILE, None)

        self.assertLoggedEqual('instruction file unchanged', DEFAULT_INSTRUCTIONS_FILE, dialog.fields['instruction_file'].GetValue())
