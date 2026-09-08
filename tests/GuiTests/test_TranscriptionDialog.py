"""Exercise transcription dialog lifetime and global settings persistence."""
import os
import time
from datetime import timedelta
from threading import Event
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QMessageBox

from GuiSubtrans.SettingsDialog import SettingsDialog
from GuiSubtrans.Widgets.TranscriptionDialog import TranscriptionDialog
from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Options import Options
from PySubtrans.SubtitleBuilder import SubtitleBuilder
from PySubtrans.SubtitleProject import SubtitleProject
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
        with patch('PySubtrans.Transcription.AudioExtractor.CheckFfmpegAvailable'):
            self.coordinator = TranscriptionCoordinator(FakeTranscriptionProvider())
        self.started = Event()
        self.release = Event()
        self.project = SubtitleProject(persistent=False)
        builder = SubtitleBuilder()
        builder.AddScene()
        builder.BuildLine(timedelta(), timedelta(seconds=1), 'Recovered text')
        self.project.subtitles = builder.Build()
        for method in ('_save_transcription', '_record_dependency_evidence', '_record_torch_device'):
            patcher = patch.object(self.dialog, method, return_value=None)
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        self.release.set()
        self.coordinator.Abort()
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            thread = self.dialog.thread
            if thread is not None:
                thread.quit()
                thread.wait(2000)
            self.application.processEvents()
            self.dialog.project = None
            self.dialog.close()
            self.dialog.deleteLater()
            self.application.processEvents()
        super().tearDown()

    def _start_worker(self) -> None:
        def create_project(*args, **kwargs) -> SubtitleProject:
            self.started.set()
            self.release.wait(3)
            self.coordinator.status = (TranscriptionStatus.INCOMPLETE if self.coordinator.aborted
                                       else TranscriptionStatus.COMPLETED)
            return self.project

        patcher = patch.object(self.coordinator, 'CreateTranscriptionProject', side_effect=create_project)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.dialog.media_path = 'readme.md'
        self.dialog.show()
        with patch.object(self.dialog, '_build_coordinator', return_value=self.coordinator):
            self.dialog._start_transcription()
        self.assertLoggedTrue('worker started', self.started.wait(1))

    def _await_thread(self) -> None:
        deadline = time.monotonic() + 3
        while self.dialog.thread is not None and time.monotonic() < deadline:
            self.application.processEvents()
            time.sleep(0.01)
        self.assertLoggedEqual('worker thread released', None, self.dialog.thread)

    def test_reject_aborts_and_preserves_partial_results(self) -> None:
        """Close/Escape cannot hide a running worker or discard its partial result."""
        self._start_worker()
        self.dialog.reject()
        self.assertLoggedTrue('abort requested', self.coordinator.aborted)
        self.assertLoggedTrue('dialog remains visible while stopping', self.dialog.isVisible())
        self.release.set()
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No) as confirm:
            self._await_thread()
        self.assertLoggedEqual('discard confirmation offered', 1, confirm.call_count)
        self.assertLoggedTrue('partial results remain visible', self.dialog.isVisible())
        self.assertLoggedEqual('partial project retained', self.project, self.dialog.project)
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
        self.assertLoggedEqual('completed project returned', self.project, self.dialog.project)

    def test_result_signal_does_not_enable_actions_before_thread_finished(self) -> None:
        """A queued result must not allow starting a second worker prematurely."""
        self.dialog.coordinator = self.coordinator
        self.coordinator.status = TranscriptionStatus.COMPLETED
        self.dialog._worker_active = True
        self.dialog._on_finished(self.project)
        self.assertLoggedFalse('back disabled until thread stops', self.dialog.back_button.isEnabled())
        button = self.dialog.button_box.button(QDialogButtonBox.StandardButton.Open)
        self.assertLoggedFalse('open disabled until thread stops', button.isEnabled())
        self.assertLoggedEqual('acceptance deferred', QDialog.DialogCode.Rejected, self.dialog.result())
        self.dialog._on_worker_thread_finished()
        self.assertLoggedEqual('acceptance after completion', QDialog.DialogCode.Accepted, self.dialog.result())


class TestTranscriptionGlobalSettings(LoggedTestCase):
    application : QApplication

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        existing = QApplication.instance()
        cls.application = existing if isinstance(existing, QApplication) else QApplication([])

    def test_cleanup_change_and_accept_write_global_option(self) -> None:
        """The cleanup checkbox writes a global value even before providers load."""
        options = Options({'postprocess_transcription': True})
        with patch.object(SettingsDialog, '_refresh_transcription_providers'), \
                patch.object(SettingsDialog, '_initialise_translation_provider'):
            dialog = SettingsDialog(options)
        try:
            dialog._on_setting_changed('Transcription', 'postprocess_transcription', False)
            self.assertLoggedEqual('global value changed immediately', False, dialog.settings['postprocess_transcription'])
            field = dialog.widgets['postprocess_transcription']
            field.SetValue(False)
            dialog.settings['transcription_provider'] = 'Muse'
            dialog.accept()
            self.assertLoggedEqual('global value accepted', False, dialog.settings['postprocess_transcription'])
            namespace = dialog.settings.get_dict('provider_settings').get('Muse Transcription', {})
            self.assertLoggedNotIn('cleanup is not provider specific', 'postprocess_transcription', namespace)
            self.assertLoggedEqual('input options unchanged until caller saves', True, options['postprocess_transcription'])
        finally:
            dialog.deleteLater()
            self.application.processEvents()
