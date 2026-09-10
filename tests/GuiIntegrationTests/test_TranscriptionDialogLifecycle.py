"""Exercise real Qt worker and transcription dialog lifetime."""
import os
import time
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QMessageBox

from GuiSubtrans.CommandQueue import CommandQueue
from GuiSubtrans.Commands.TranscribeMediaCommand import TranscribeMediaCommand
from GuiSubtrans.Widgets.TranscriptionDialog import TranscriptionDialog
from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Options import Options
from PySubtrans.SubtitleBuilder import SubtitleBuilder
from PySubtrans.Subtitles import Subtitles
from PySubtrans.Transcription.TranscriptionCoordinator import TranscriptionCoordinator, TranscriptionStatus
from tests.PySubtransTests.test_Transcription import FakeTranscriptionProvider


class TestTranscriptionDialogLifecycle(LoggedTestCase):
    application : QApplication

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        existing = QApplication.instance()
        cls.application = existing if isinstance(existing, QApplication) else QApplication([])

    def setUp(self) -> None:
        super().setUp()
        with patch.object(TranscriptionDialog, '_refresh_providers'):
            self.dialog = TranscriptionDialog(Options())
        self.queue = CommandQueue(self.dialog)
        self.dialog.commandRequested.connect(self.queue.AddCommand)
        with patch('PySubtrans.Transcription.AudioExtractor.CheckFfmpegAvailable'):
            self.coordinator = TranscriptionCoordinator(FakeTranscriptionProvider())
        self.started = Event()
        self.release = Event()
        builder = SubtitleBuilder()
        builder.AddScene()
        builder.BuildLine(timedelta(), timedelta(seconds=1), 'Recovered text')
        self.subtitles : Subtitles = builder.Build()
        for method in ('_record_dependency_evidence',):
            patcher = patch.object(self.dialog, method, return_value=None)
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        self.release.set()
        self.coordinator.Abort()
        self.queue.Stop()
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            self.application.processEvents()
            self.dialog.subtitles = None
            self.dialog.close()
            self.dialog.deleteLater()
            self.application.processEvents()
        super().tearDown()

    def _start_worker(self) -> None:
        def create_transcription(*args, **kwargs) -> Subtitles:
            self.started.set()
            self.release.wait(3)
            self.coordinator.status = (TranscriptionStatus.INCOMPLETE if self.coordinator.aborted
                                       else TranscriptionStatus.COMPLETED)
            self.coordinator.transcribed_lines = self.subtitles.linecount
            return self.subtitles

        patcher = patch.object(self.coordinator, 'CreateTranscription', side_effect=create_transcription)
        patcher.start()
        self.addCleanup(patcher.stop)
        coordinator_patcher = patch('GuiSubtrans.Commands.TranscribeMediaCommand.TranscriptionCoordinator', return_value=self.coordinator)
        coordinator_patcher.start()
        self.addCleanup(coordinator_patcher.stop)
        self.dialog.media_path = 'readme.md'
        self.dialog.show()
        command = TranscribeMediaCommand(self.coordinator.provider, self.dialog.media_path,
                                         self.coordinator.settings, Options(), save_transcription=True)
        with patch.object(self.dialog, '_build_command', return_value=command):
            self.dialog._start_transcription()
        self.assertLoggedTrue('queue command started', self.started.wait(1))

    def _await_thread(self) -> None:
        deadline = time.monotonic() + 3
        while self.dialog.active_command is not None and time.monotonic() < deadline:
            self.application.processEvents()
            time.sleep(0.01)
        self.assertLoggedIsNone('queue command released', self.dialog.active_command)

    def _await_file(self, path : Path) -> None:
        deadline = time.monotonic() + 3
        while not path.is_file() and time.monotonic() < deadline:
            self.application.processEvents()
            time.sleep(0.01)
        self.assertLoggedTrue('queued save completed', path.is_file())

    def test_reject_aborts_and_preserves_partial_results(self) -> None:
        """Close/Escape cannot hide a running worker or discard its partial result."""
        with TemporaryDirectory() as directory:
            output_path = Path(directory) / 'partial.srt'
            self._start_worker()
            self.dialog.reject()
            self.assertLoggedTrue('abort requested', self.coordinator.aborted)
            self.assertLoggedTrue('dialog remains visible while stopping', self.dialog.isVisible())
            self.release.set()
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No) as confirm, \
                    patch('GuiSubtrans.Commands.TranscribeMediaCommand.GetOutputPath', return_value=str(output_path)):
                self._await_thread()
                self._await_file(output_path)
                self.assertLoggedIn('actual subtitle content written', 'Recovered text', output_path.read_text(encoding='utf-8-sig'))
        self.assertLoggedEqual('discard confirmation offered', 1, confirm.call_count)
        self.assertLoggedTrue('partial results remain visible', self.dialog.isVisible())
        self.assertLoggedEqual('partial subtitles retained', self.subtitles, self.dialog.subtitles)
        button = self.dialog.button_box.button(QDialogButtonBox.StandardButton.Open)
        self.assertLoggedTrue('partial project can be opened', button.isEnabled())

    def test_window_close_waits_for_worker(self) -> None:
        """The window close event follows the same nonblocking cancellation path."""
        self._start_worker()
        self.dialog.close()
        self.assertLoggedTrue('window close requests abort', self.coordinator.aborted)
        self.assertLoggedTrue('window retained during abort', self.dialog.isVisible())
        self.release.set()
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            self._await_thread()
        self.assertLoggedFalse('window closes after worker and confirmation', self.dialog.isVisible())

    def test_clean_completion_opens_project_after_thread_stops(self) -> None:
        """The normal worker path accepts the completed project safely."""
        self._start_worker()
        self.release.set()
        self._await_thread()
        self.assertLoggedEqual('clean result accepted', QDialog.DialogCode.Accepted, self.dialog.result())
        self.assertLoggedEqual('completed subtitles returned', self.subtitles, self.dialog.subtitles)

    def test_actions_stay_disabled_until_queue_completion(self) -> None:
        """Do not enable project opening or retry until queue completion."""
        self._start_worker()
        self.assertLoggedFalse('back disabled during execution', self.dialog.back_button.isEnabled())
        button = self.dialog.button_box.button(QDialogButtonBox.StandardButton.Open)
        self.assertLoggedIsNotNone('open button exists', button)
        if button is None:
            return
        self.assertLoggedFalse('open disabled during execution', button.isEnabled())
        self.release.set()
        self._await_thread()
        self.assertLoggedTrue('back enabled after queue completion', self.dialog.back_button.isEnabled())
        self.assertLoggedTrue('open enabled after queue completion', button.isEnabled())
        self.assertLoggedEqual('acceptance after completion', QDialog.DialogCode.Accepted, self.dialog.result())
