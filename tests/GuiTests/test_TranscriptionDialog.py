"""Exercise synchronous transcription settings and result handling."""
import os
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication

from GuiSubtrans.Commands.TranscribeMediaCommand import TranscribeMediaCommand
from GuiSubtrans.SettingsDialog import SettingsDialog
from GuiSubtrans.Widgets.OptionsWidgets import (
    CheckboxOptionWidget,
    DropdownOptionWidget,
    FloatOptionWidget,
    IntegerOptionWidget,
)
from GuiSubtrans.Widgets.TranscriptionDialog import TranscriptionDialog
from GuiSubtrans.Widgets.TranscriptionRunProgress import _format_timestamp
from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Helpers.Tests import skip_if_debugger_attached
from PySubtrans.Options import Options
from PySubtrans.SettingsType import SettingsType
from PySubtrans.Transcription.TranscriptionOutcome import TranscriptionStatus
from tests.PySubtransTests.test_Transcription import FakeTranscriptionProvider


class TestTranscriptionRunProgressFormatting(LoggedTestCase):
    """Verify readable timecodes used by the transcription progress display."""

    def test_sub_minute_timestamps_include_minutes(self) -> None:
        """Sub-minute timestamps use the same m:ss shape as longer timestamps."""
        self.assertLoggedEqual('sub-minute timestamp', '0:15', _format_timestamp(15.0))
        self.assertLoggedEqual('zero timestamp', '0:00', _format_timestamp(0.0))
        self.assertLoggedEqual('minute timestamp', '01:05', _format_timestamp(65.0))


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

    def test_ffmpeg_path_is_saved_as_global_option(self) -> None:
        """The executable path is not copied into a provider namespace."""
        options = Options()
        with patch.object(SettingsDialog, '_refresh_transcription_providers'), \
                patch.object(SettingsDialog, '_initialise_translation_provider'):
            dialog = SettingsDialog(options)
        try:
            path = r'C:\tools\ffmpeg.exe'
            dialog._on_setting_changed(SettingsDialog.TRANSCRIPTION_SECTION, 'ffmpeg_path', path)
            dialog.widgets['ffmpeg_path'].SetValue(path)
            dialog.accept()

            self.assertLoggedEqual('global ffmpeg path', path, dialog.settings.get_str('ffmpeg_path'))
            provider_settings = dialog.settings.get_dict('provider_settings')
            transcription_settings = provider_settings.get('OpenRouter Transcription', {})
            self.assertLoggedNotIn('ffmpeg path is not provider-specific', 'ffmpeg_path', transcription_settings)
        finally:
            dialog.deleteLater()
            self.application.processEvents()

    def test_ffmpeg_path_placeholder_comes_from_option_definition(self) -> None:
        """Text-field guidance is applied from the declarative option metadata."""
        options = Options()
        with patch.object(SettingsDialog, '_refresh_transcription_providers'), \
                patch.object(SettingsDialog, '_initialise_translation_provider'):
            dialog = SettingsDialog(options)
        try:
            option_definition = SettingsDialog.SECTIONS[SettingsDialog.TRANSCRIPTION_SECTION]['ffmpeg_path']
            self.assertLoggedEqual(
                'ffmpeg placeholder',
                option_definition[2],
                dialog.widgets['ffmpeg_path'].text_field.placeholderText())
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
        command.audioProgressed.connect(dialog._on_audio_progress)
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

    def test_audio_progress_drives_eta_without_chunk_total(self) -> None:
        """Audio progress restores ETA while the streamed chunk total is unknown."""
        options = Options()
        with patch.object(TranscriptionDialog, '_refresh_providers'):
            dialog = TranscriptionDialog(options)
        try:
            dialog.run_progress.started = 100.0
            dialog.run_progress.OnProgress(1, 0, '0.0s-10.0s')
            with patch('GuiSubtrans.Widgets.TranscriptionRunProgress.time.monotonic', return_value=160.0):
                dialog._on_audio_progress(10.0, 100.0)

            self.assertLoggedIn('audio-based eta', 'about 9:00 left', dialog.status_label.text())
        finally:
            dialog.deleteLater()
            self.application.processEvents()

    def test_immediate_command_completion_returns_to_done_state(self) -> None:
        """A command finishing immediately does not leave the dialog running."""
        options = Options()
        with patch.object(TranscriptionDialog, '_refresh_providers'):
            dialog = TranscriptionDialog(options)
        try:
            command = TranscribeMediaCommand(FakeTranscriptionProvider(), 'media.wav', SettingsType())
            dialog.media_path = __file__

            def complete_immediately(submitted : TranscribeMediaCommand) -> None:
                submitted.commandCompleted.emit(submitted)

            dialog.commandRequested.connect(complete_immediately)
            try:
                with patch.object(dialog, '_build_command', return_value=command):
                    dialog._start_transcription()
                    for _event_pass in range(3):
                        self.application.processEvents()

                self.assertLoggedEqual('dialog phase after immediate completion', 'done', dialog._phase)
                self.assertLoggedIsNone('immediate completion releases command', dialog.active_command)
                self.assertLoggedFalse('abort control hidden after completion', dialog.abort_button.isVisible())
            finally:
                dialog.commandRequested.disconnect(complete_immediately)
        finally:
            dialog.deleteLater()
            self.application.processEvents()


class TestTranscriptionDialogLayout(LoggedTestCase):
    application : QApplication

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        existing = QApplication.instance()
        cls.application = existing if isinstance(existing, QApplication) else QApplication([])

    def test_provider_rows_inserted_into_single_form(self) -> None:
        """Provider rows are dynamically inserted into and removed from the main form."""
        options = Options()
        with patch.object(TranscriptionDialog, '_refresh_providers'):
            dialog = TranscriptionDialog(options)
        try:
            initial_row_count = dialog.form.rowCount()
            # Initial static rows: Media file, Audio track, Provider, Min chunk, Max chunk, Save, Postprocess
            self.assertLoggedEqual('initial row count', 7, initial_row_count)

            # Assign a fake provider with options and rebuild
            provider = FakeTranscriptionProvider()
            provider.GetOptions = lambda settings: {'model': (['model-a', 'model-b'], None), 'language': (str, None)}  # type: ignore
            dialog.provider = provider
            dialog._rebuild_provider_form()

            self.assertLoggedEqual('provider row count tracked', 2, dialog._provider_row_count)
            self.assertLoggedEqual('form row count with provider options', 9, dialog.form.rowCount())
            self.assertLoggedIn('provider field registered', 'model', dialog.provider_fields)
            self.assertLoggedIn('provider field registered', 'language', dialog.provider_fields)

            # Rebuild with different options
            provider.GetOptions = lambda settings: {'single_opt': (bool, None)}  # type: ignore
            dialog._rebuild_provider_form()

            self.assertLoggedEqual('provider row count updated', 1, dialog._provider_row_count)
            self.assertLoggedEqual('form row count after rebuild', 8, dialog.form.rowCount())

            # Clear provider
            dialog.provider = None
            dialog._rebuild_provider_form()
            self.assertLoggedEqual('row count restored to initial', initial_row_count, dialog.form.rowCount())
            self.assertLoggedEqual('provider row count zeroed', 0, dialog._provider_row_count)
        finally:
            dialog.deleteLater()
            self.application.processEvents()

    def test_invalid_chunk_bounds_are_rejected_before_command_creation(self) -> None:
        """Invalid chunk bounds are reported before a worker can start."""
        options = Options()
        with patch.object(TranscriptionDialog, '_refresh_providers'):
            dialog = TranscriptionDialog(options)
        try:
            dialog.provider = FakeTranscriptionProvider()
            dialog.media_path = __file__
            dialog.fields['min_chunk_seconds'].SetValue(60.0)
            dialog.fields['max_chunk_seconds'].SetValue(10.0)

            with patch('GuiSubtrans.Widgets.TranscriptionDialog.TranscribeMediaCommand') as command_factory:
                command = dialog._build_command()

            self.assertLoggedIsNone('invalid bounds produce no command', command)
            self.assertLoggedEqual('command construction skipped', 0, command_factory.call_count)
            self.assertLoggedIn('validation message', 'maximum chunk length', dialog.status_label.text())
        finally:
            dialog.deleteLater()
            self.application.processEvents()

    def test_build_command_passes_global_ffmpeg_path(self) -> None:
        """Transcription runs receive the configured executable path."""
        path = r'C:\tools\ffmpeg.exe'
        options = Options({'ffmpeg_path': path})
        with patch.object(TranscriptionDialog, '_refresh_providers'):
            dialog = TranscriptionDialog(options)
        try:
            dialog.provider = FakeTranscriptionProvider()
            dialog.media_path = __file__
            command = dialog._build_command()

            self.assertLoggedIsNotNone('command created', command)
            if command is not None:
                self.assertLoggedEqual('configured ffmpeg path', path,
                                       command.settings.get_str('ffmpeg_path'))
        finally:
            dialog.deleteLater()
            self.application.processEvents()

    def test_option_widgets_have_valid_size_hints(self) -> None:
        """Option widgets report valid size hints and non-zero layouts."""
        int_w = IntegerOptionWidget('int_key', 10)
        float_w = FloatOptionWidget('float_key', 10.0)
        cb_w = CheckboxOptionWidget('cb_key', True)
        dd_w = DropdownOptionWidget('dd_key', ['a', 'b'], 'a')

        self.assertLoggedGreater('int widget width hint', int_w.sizeHint().width(), 0)
        self.assertLoggedGreater('float widget width hint', float_w.sizeHint().width(), 0)
        self.assertLoggedGreater('checkbox widget width hint', cb_w.sizeHint().width(), 0)
        self.assertLoggedGreater('dropdown widget width hint', dd_w.sizeHint().width(), 0)
