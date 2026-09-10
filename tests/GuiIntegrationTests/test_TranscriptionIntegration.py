"""Integration coverage for transcription queue and project handoff behavior."""
import os
import time
from datetime import timedelta
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QDialog, QMainWindow

from GuiSubtrans.Commands.TranscribeMediaCommand import TranscribeMediaCommand
from GuiSubtrans.GuiInterface import GuiInterface
from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Options import Options
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleBuilder import SubtitleBuilder
from PySubtrans.Subtitles import Subtitles
from PySubtrans.Transcription.TranscriptionCoordinator import TranscriptionStatus
from tests.PySubtransTests.test_Transcription import FakeTranscriptionProvider


class _DialogStub(QObject):
    commandRequested = Signal(object)

    def __init__(self, subtitles : Subtitles|None, result : QDialog.DialogCode,
                 requested_command : object|None = None) -> None:
        super().__init__()
        self.subtitles = subtitles
        self.media_path = 'media.wav'
        self.result_code = result
        self.requested_command = requested_command

    def exec(self) -> QDialog.DialogCode:
        if self.requested_command is not None:
            self.commandRequested.emit(self.requested_command)
        return self.result_code


class TestTranscriptionIntegration(LoggedTestCase):
    application : QApplication

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        existing = QApplication.instance()
        cls.application = existing if isinstance(existing, QApplication) else QApplication([])

    def setUp(self) -> None:
        super().setUp()
        settings_patcher = patch.object(Options, 'SaveSettings')
        settings_patcher.start()
        self.addCleanup(settings_patcher.stop)
        self.window = QMainWindow()
        with patch('PySubtrans.TranslationProvider.TranslationProvider.get_providers', return_value=[]):
            self.gui = GuiInterface(self.window, Options())
        self.old_model = self.gui.datamodel
        self.completed = []
        self.gui.commandComplete.connect(self.completed.append)
        self.addCleanup(self.gui.command_queue.Stop)
        self.addCleanup(self.window.deleteLater)

    def _subtitles(self) -> Subtitles:
        builder = SubtitleBuilder()
        builder.AddScene()
        builder.BuildLine(timedelta(), timedelta(seconds=1), 'Transcribed text')
        return builder.Build()

    def _command(self, status : TranscriptionStatus, subtitles : Subtitles|None = None) -> tuple[TranscribeMediaCommand, Mock]:
        coordinator = Mock(status=status, last_error=None, partial_subtitles=None, transcribed_lines=1)
        coordinator.CreateTranscription.return_value = subtitles
        command = TranscribeMediaCommand(FakeTranscriptionProvider(), 'media.wav', SettingsType(), Options())
        return command, coordinator

    def _wait_for_queue(self) -> None:
        expected_completions = len(self.completed) + 1
        deadline = time.monotonic() + 3
        while len(self.completed) < expected_completions and time.monotonic() < deadline:
            self.application.processEvents()
            time.sleep(0.01)
        self.assertLoggedFalse('queue drained', self.gui.command_queue.has_commands)
        self.assertLoggedEqual('GuiInterface completion delivered', expected_completions, len(self.completed))

    def test_real_queue_completion_preserves_current_model_until_acceptance(self) -> None:
        command, coordinator = self._command(TranscriptionStatus.COMPLETED, self._subtitles())
        model_changes = []
        completions = []
        self.gui.dataModelChanged.connect(model_changes.append)
        command.commandCompleted.connect(completions.append)
        self.gui.command_queue.undo_stack = [Mock()]
        with patch('GuiSubtrans.Commands.TranscribeMediaCommand.TranscriptionCoordinator', return_value=coordinator):
            self.gui.QueueCommand(command)
            self._wait_for_queue()
        self.assertLoggedEqual('current model retained after command', self.old_model, self.gui.datamodel)
        self.assertLoggedIsNotNone('transcription result retained', command.subtitles)
        self.assertLoggedEqual('completion observed by the command owner', [command], completions)
        self.assertLoggedEqual('no model reset emitted', [], model_changes)
        self.assertLoggedEqual('successful open command clears old undo history', [], self.gui.command_queue.undo_stack)

    def test_failed_stopped_and_aborted_completion_preserve_current_model(self) -> None:
        cases = [
            (TranscriptionStatus.FAILED, None),
            (TranscriptionStatus.INCOMPLETE, None),
            (TranscriptionStatus.INCOMPLETE, 'early'),
            (TranscriptionStatus.INCOMPLETE, 'abort'),
        ]
        for status, stop in cases:
            command, coordinator = self._command(status, self._subtitles())
            if stop == 'early':
                command.FinishEarly()
            elif stop == 'abort':
                command.Abort()
            with patch('GuiSubtrans.Commands.TranscribeMediaCommand.TranscriptionCoordinator', return_value=coordinator):
                self.gui.QueueCommand(command)
                self._wait_for_queue()
            self.assertLoggedEqual('failed, stopped or aborted model retained', self.old_model, self.gui.datamodel)

    def test_accepted_project_installs_once_and_partial_acceptance_clears_history(self) -> None:
        dialog = _DialogStub(self._subtitles(), QDialog.DialogCode.Accepted)
        self.gui.command_queue.undo_stack = [Mock()]
        with patch('GuiSubtrans.GuiInterface.TranscriptionDialog', return_value=dialog), \
                patch.object(self.gui, 'ShowNewProjectSettings'), \
                patch.object(self.gui, 'SetDataModel', wraps=self.gui.SetDataModel) as set_model:
            self.gui.ShowTranscriptionDialog()
        self.assertLoggedEqual('accepted model installed once', 1, set_model.call_count)
        self.assertLoggedEqual('partial acceptance clears history', 0, len(self.gui.command_queue.undo_stack))

    def test_discarded_dialog_preserves_current_model(self) -> None:
        dialog = _DialogStub(self._subtitles(), QDialog.DialogCode.Rejected)
        with patch('GuiSubtrans.GuiInterface.TranscriptionDialog', return_value=dialog), \
                patch.object(self.gui, 'SetDataModel') as set_model:
            self.gui.ShowTranscriptionDialog()
        self.assertLoggedEqual('discard keeps current model', self.old_model, self.gui.datamodel)
        self.assertLoggedEqual('discard does not install model', 0, set_model.call_count)

    def test_busy_entry_guard_covers_pending_and_running_queue_commands(self) -> None:
        for queued_command in (Mock(started=False), Mock(started=True)):
            self.gui.command_queue.queue.append(queued_command)
            with patch('GuiSubtrans.GuiInterface.TranscriptionDialog') as dialog_type:
                self.gui.ShowTranscriptionDialog()
            self.assertLoggedEqual('busy guard does not open dialog', 0, dialog_type.call_count)
            self.gui.command_queue.queue.clear()

    def test_dialog_requests_are_queued_like_any_other_command(self) -> None:
        """The dialog's request signal goes straight to the generic queue entry point."""
        requested = Mock()
        dialog = _DialogStub(self._subtitles(), QDialog.DialogCode.Accepted, requested)
        with patch('GuiSubtrans.GuiInterface.TranscriptionDialog', return_value=dialog), \
                patch.object(self.gui, 'QueueCommand') as queue_command, \
                patch.object(self.gui, 'ShowNewProjectSettings'):
            self.gui.ShowTranscriptionDialog()
        self.assertLoggedEqual('dialog command submitted to queue', 1, queue_command.call_count)
        self.assertLoggedIs('transcription command submitted', requested, queue_command.call_args.args[0])

    def test_command_completion_schedules_autosave(self) -> None:
        """The generic completion handler schedules autosave for a dirty idle project."""
        self.gui.datamodel = Mock(autosave_enabled=True, project=Mock(needs_writing=True))
        command = Mock(succeeded=True, model_updates=[],
                       datamodel=self.gui.datamodel, queued_datamodel=self.gui.datamodel)
        with patch.object(self.gui._autosave_timer, 'start') as autosave:
            self.gui._on_command_complete(command)
        self.assertLoggedEqual('autosave scheduled', 1, autosave.call_count)
