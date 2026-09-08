"""Tests for MainToolbar queue-state driven action availability."""
import os
from unittest.mock import Mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication

from GuiSubtrans.MainToolbar import MainToolbar
from PySubtrans.Helpers.TestCases import LoggedTestCase


class TestMainToolbarTranscribeButton(LoggedTestCase):
    application : QApplication

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        existing = QApplication.instance()
        cls.application = existing if isinstance(existing, QApplication) else QApplication([])

    def _toolbar(self, has_commands : bool) -> MainToolbar:
        """Create a toolbar against a stub interface with the given queue state."""
        command_queue = Mock()
        command_queue.has_commands = has_commands
        command_queue.Contains.return_value = False
        command_queue.has_blocking_commands = False
        command_queue.can_undo = False
        command_queue.can_redo = False
        datamodel = Mock()
        datamodel.is_project_initialised = True
        datamodel.allow_multithreaded_translation = True
        gui = Mock()
        gui.GetCommandQueue.return_value = command_queue
        gui.GetDataModel.return_value = datamodel
        return MainToolbar(gui)

    def test_transcribe_enabled_when_queue_is_idle(self) -> None:
        """The transcribe action is available while no commands are queued."""
        toolbar = self._toolbar(has_commands=False)
        self.addCleanup(toolbar.deleteLater)
        toolbar.UpdateToolbar()
        self.assertLoggedTrue('transcribe available when idle', toolbar.GetAction('Transcribe').isEnabled())

    def test_transcribe_disabled_while_commands_are_pending(self) -> None:
        """The transcribe action is unavailable while commands are queued or running."""
        toolbar = self._toolbar(has_commands=True)
        self.addCleanup(toolbar.deleteLater)
        toolbar.UpdateToolbar()
        self.assertLoggedFalse('transcribe disabled while busy', toolbar.GetAction('Transcribe').isEnabled())
