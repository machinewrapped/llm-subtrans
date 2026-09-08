"""Exercise transcription dialog lifetime and global settings persistence."""
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
from GuiSubtrans.SettingsDialog import SettingsDialog
from GuiSubtrans.Widgets.TranscriptionDialog import TranscriptionDialog
from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Helpers.Tests import skip_if_debugger_attached
from PySubtrans.Options import Options
from PySubtrans.SettingsType import SettingsType
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
        self.queue = CommandQueue(self.dialog)
        self.dialog.commandRequested.connect(self.queue.AddCommand)
        with patch('PySubtrans.Transcription.AudioExtractor.CheckFfmpegAvailable'):
            self.coordinator = TranscriptionCoordinator(FakeTranscriptionProvider())
        self.started = Event()
        self.release = Event()
        self.project = SubtitleProject(persistent=False)
        builder = SubtitleBuilder()
        builder.AddScene()
        builder.BuildLine(timedelta(), timedelta(seconds=1), 'Recovered text')
        self.project.subtitles = builder.Build()
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


class TestTranscriptionRunEvidence(LoggedTestCase):
    """Run-completion evidence recording on the dialog itself."""
    application : QApplication

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        existing = QApplication.instance()
        cls.application = existing if isinstance(existing, QApplication) else QApplication([])

    def _completed_command(self) -> TranscribeMediaCommand:
        command = TranscribeMediaCommand(FakeTranscriptionProvider(), 'media.wav', SettingsType())
        command.ffmpeg_available = True
        command.torch_device = 'cuda:0'
        command.status = TranscriptionStatus.COMPLETED
        return command

    def _observe(self, dialog : TranscriptionDialog, command : TranscribeMediaCommand) -> None:
        """Wire the dialog to the command the same way a real run does."""
        dialog.active_command = command
        command.progressed.connect(dialog._on_progress)
        command.segmented.connect(dialog._on_segment)
        command.commandCompleted.connect(dialog._on_command_completed)

    def test_completion_records_dependency_evidence(self) -> None:
        """A completed run persists proven dependency facts for future sessions."""
        options = Options({'transcription_ffmpeg_available': None, 'transcription_torch_device': 'Unknown'})
        with patch.object(TranscriptionDialog, '_refresh_providers'):
            dialog = TranscriptionDialog(options)
        try:
            command = self._completed_command()
            self._observe(dialog, command)
            with patch.object(Options, 'SaveSettings') as save_settings:
                dialog._on_command_completed(command)
            self.assertLoggedEqual('settings persisted once', 1, save_settings.call_count)
            self.assertLoggedEqual('ffmpeg evidence recorded', True, options.get('transcription_ffmpeg_available'))
            self.assertLoggedEqual('torch device recorded', 'cuda:0', options.get_str('transcription_torch_device'))
            self.assertLoggedIsNone('dialog released the command', dialog.active_command)
        finally:
            dialog.deleteLater()
            self.application.processEvents()

    @skip_if_debugger_attached
    def test_completion_survives_settings_save_failure(self) -> None:
        """A failed settings write does not disrupt the completion flow."""
        options = Options()
        with patch.object(TranscriptionDialog, '_refresh_providers'):
            dialog = TranscriptionDialog(options)
        try:
            command = self._completed_command()
            self._observe(dialog, command)
            with patch.object(Options, 'SaveSettings', side_effect=RuntimeError('settings unavailable')):
                dialog._on_command_completed(command)
            self.assertLoggedIsNone('dialog released the command', dialog.active_command)
            self.assertLoggedEqual('results phase reached', 'done', dialog._phase)
        finally:
            dialog.deleteLater()
            self.application.processEvents()
