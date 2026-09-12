"""Tests for queue-owned transcription execution."""
import os
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from GuiSubtrans.Commands.SaveSubtitleFile import SaveSubtitleFile
from GuiSubtrans.Commands.TranscribeMediaCommand import TranscribeMediaCommand
from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Helpers.Tests import skip_if_debugger_attached
from PySubtrans.Options import Options
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.SubtitleBuilder import SubtitleBuilder
from PySubtrans.Transcription.TranscriptionEvents import TranscriptionEvents
from PySubtrans.Transcription.TranscriptionOutcome import TranscriptionOutcome, TranscriptionStatus
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionSegment
from tests.PySubtransTests.test_Transcription import FakeTranscriptionProvider


class TestTranscribeMediaCommand(LoggedTestCase):
    """Run without provider requests, real models, or external media tools."""

    def setUp(self) -> None:
        super().setUp()
        self.provider = FakeTranscriptionProvider()
        builder = SubtitleBuilder()
        builder.AddScene()
        builder.BuildLine(timedelta(), timedelta(seconds=1), 'Recovered text')
        self.subtitles = builder.Build()
        self.coordinator = Mock()
        self.coordinator.CreateTranscription.return_value = TranscriptionOutcome(
            TranscriptionStatus.COMPLETED, self.subtitles, transcribed_lines=1)

    def test_completed_run_forwards_progress_and_returns_project(self) -> None:
        subtitles = Mock()
        coordinator = Mock(events=TranscriptionEvents())

        segment_events = []
        segment = TranscriptionSegment(timedelta(), timedelta(seconds=1), 'Recovered text')

        def create_transcription(media, options, **kwargs):
            coordinator.events.progress.send(coordinator, done=1, total=2, span='0:00-0:10')
            coordinator.events.audio_progress.send(coordinator, processed=10.0, total=20.0)
            coordinator.events.segment.send(coordinator, segment=segment)
            return TranscriptionOutcome(TranscriptionStatus.COMPLETED, subtitles, transcribed_lines=1)

        coordinator.CreateTranscription.side_effect = create_transcription
        provider = Mock(settings=SettingsType())
        command = TranscribeMediaCommand(provider, 'media.wav', SettingsType(), Options())
        progress = []
        command.progressed.connect(lambda done, total, span: progress.append((done, total, span)))
        audio_progress = []
        command.audioProgressed.connect(lambda processed, total: audio_progress.append((processed, total)))
        command.segmented.connect(segment_events.append)
        with patch('GuiSubtrans.Commands.TranscribeMediaCommand.TranscriptionCoordinator', return_value=coordinator):
            result = command.execute()

        self.assertLoggedTrue('completed command succeeds', result)
        self.assertLoggedEqual('subtitles retained', subtitles, command.subtitles)
        self.assertLoggedEqual('progress forwarded', [(1, 2, '0:00-0:10')], progress)
        self.assertLoggedEqual('audio progress forwarded', [(10.0, 20.0)], audio_progress)
        self.assertLoggedEqual('segment forwarded', [segment], segment_events)

    def test_incomplete_run_returns_failure_and_retains_project(self) -> None:
        subtitles = Mock()
        coordinator = Mock()
        coordinator.CreateTranscription.return_value = TranscriptionOutcome(TranscriptionStatus.INCOMPLETE, subtitles)
        command = TranscribeMediaCommand(Mock(settings=SettingsType()), 'media.wav', SettingsType(), Options())
        with patch('GuiSubtrans.Commands.TranscribeMediaCommand.TranscriptionCoordinator', return_value=coordinator):
            result = command.execute()

        self.assertLoggedFalse('incomplete command fails', result)
        self.assertLoggedEqual('subtitles retained', subtitles, command.subtitles)

    @skip_if_debugger_attached
    def test_exception_is_reported_without_saving(self) -> None:
        coordinator = Mock()
        coordinator.CreateTranscription.side_effect = RuntimeError('provider failed')
        command = TranscribeMediaCommand(Mock(settings=SettingsType()), 'media.wav', SettingsType(), Options(), save_transcription=True)
        with patch('GuiSubtrans.Commands.TranscribeMediaCommand.TranscriptionCoordinator', return_value=coordinator):
            result = command.execute()

        self.assertLoggedFalse('failed command returns failure', result)
        self.assertLoggedEqual('failure status recorded', TranscriptionStatus.FAILED, command.status)
        self.assertLoggedIsNone('no subtitles from an exception', command.subtitles)
        self.assertLoggedIsNone('exception result not saved', command.saved_path)

    def test_failed_outcome_is_reported_without_saving(self) -> None:
        coordinator = Mock()
        coordinator.CreateTranscription.return_value = TranscriptionOutcome(
            TranscriptionStatus.FAILED, error=SubtitleError('no speech'))
        command = TranscribeMediaCommand(Mock(settings=SettingsType()), 'media.wav', SettingsType(), Options(), save_transcription=True)
        with patch('GuiSubtrans.Commands.TranscribeMediaCommand.TranscriptionCoordinator', return_value=coordinator):
            result = command.execute()

        self.assertLoggedFalse('failed outcome returns failure', result)
        self.assertLoggedEqual('failure status recorded', TranscriptionStatus.FAILED, command.status)
        self.assertLoggedEqual('error retained', 'no speech', command.error)
        self.assertLoggedIsNone('failed outcome not saved', command.saved_path)

    def test_abort_forwards_to_active_coordinator(self) -> None:
        coordinator = Mock()
        command = TranscribeMediaCommand(Mock(settings=SettingsType()), 'media.wav', SettingsType(), Options())
        command.coordinator = coordinator
        command.Abort()
        self.assertLoggedEqual('abort forwarded', 1, coordinator.Abort.call_count)

    @skip_if_debugger_attached
    def test_failure_without_results_retains_error(self) -> None:
        self.coordinator.CreateTranscription.side_effect = RuntimeError('provider failed')
        command = TranscribeMediaCommand(self.provider, 'media.wav', SettingsType())
        with patch('GuiSubtrans.Commands.TranscribeMediaCommand.TranscriptionCoordinator', return_value=self.coordinator):
            result = command.execute()
        self.assertLoggedFalse('failed command returns failure', result)
        self.assertLoggedIsNone('no fabricated subtitles', command.subtitles)
        self.assertLoggedEqual('error retained', 'provider failed', command.error)

    @skip_if_debugger_attached
    def test_constructor_failure_is_reported(self) -> None:
        command = TranscribeMediaCommand(self.provider, 'media.wav', SettingsType())
        with patch('GuiSubtrans.Commands.TranscribeMediaCommand.TranscriptionCoordinator', side_effect=RuntimeError('ffmpeg unavailable')):
            result = command.execute()
        self.assertLoggedFalse('setup failure returns failure', result)
        self.assertLoggedEqual('setup error retained', 'ffmpeg unavailable', command.error)
        self.assertLoggedEqual('setup failure status', TranscriptionStatus.FAILED, command.status)

    def test_abort_before_execution_does_not_create_coordinator(self) -> None:
        command = TranscribeMediaCommand(self.provider, 'media.wav', SettingsType())
        command.Abort()
        with patch('GuiSubtrans.Commands.TranscribeMediaCommand.TranscriptionCoordinator') as factory:
            command.run()
        self.assertLoggedEqual('no work started', 0, factory.call_count)
        self.assertLoggedTrue('cancellation retained', command.aborted)

    def test_abort_during_coordinator_creation_is_not_lost(self) -> None:
        started = Event()
        release = Event()
        command = TranscribeMediaCommand(self.provider, 'media.wav', SettingsType())

        def create_coordinator(provider, settings):
            started.set()
            release.wait(3)
            return self.coordinator

        worker = Thread(target=command.run)
        with patch('GuiSubtrans.Commands.TranscribeMediaCommand.TranscriptionCoordinator', side_effect=create_coordinator):
            worker.start()
            try:
                self.assertLoggedTrue('construction started', started.wait(1))
                command.Abort()
            finally:
                release.set()
                worker.join(3)
        self.assertLoggedFalse('worker finished', worker.is_alive())
        self.assertLoggedEqual('constructed coordinator receives abort', 1, self.coordinator.Abort.call_count)
        self.assertLoggedEqual('inference never begins', 0, self.coordinator.CreateTranscription.call_count)

    def test_active_abort_preserves_partial_result_without_saving(self) -> None:
        """A cancelled command keeps its partial result, but the queue drops its follow-ups."""
        with TemporaryDirectory() as directory:
            command = TranscribeMediaCommand(self.provider, str(Path(directory) / 'media.wav'), SettingsType(), save_transcription=True)

            def create_transcription(*args, **kwargs):
                command.Abort()
                return TranscriptionOutcome(TranscriptionStatus.INCOMPLETE, self.subtitles, transcribed_lines=1)

            self.coordinator.CreateTranscription.side_effect = create_transcription
            with patch('GuiSubtrans.Commands.TranscribeMediaCommand.TranscriptionCoordinator', return_value=self.coordinator):
                result = command.execute()
            self.assertLoggedFalse('cancelled run not successful', result)
            self.assertLoggedEqual('abort forwarded', 1, self.coordinator.Abort.call_count)
            self.assertLoggedEqual('subtitles retained', self.subtitles, command.subtitles)
            self.assertLoggedFalse('partial subtitles not written by the command', (Path(directory) / 'media.srt').is_file())
            self.assertLoggedEqual('no follow-up commands queued', 0, len(command.commands_to_queue))
            self.assertLoggedFalse('aborted run does not write dependency evidence', command.ffmpeg_available)

    def test_early_finish_preserves_partial_results_and_queues_save(self) -> None:
        """A user-requested early finish is an orderly stop: the partial save still runs."""
        with TemporaryDirectory() as directory:
            command = TranscribeMediaCommand(self.provider, str(Path(directory) / 'media.wav'), SettingsType(), save_transcription=True)

            def create_transcription(*args, **kwargs):
                command.FinishEarly()
                return TranscriptionOutcome(TranscriptionStatus.INCOMPLETE, self.subtitles, transcribed_lines=1)

            self.coordinator.CreateTranscription.side_effect = create_transcription
            with patch('GuiSubtrans.Commands.TranscribeMediaCommand.TranscriptionCoordinator', return_value=self.coordinator):
                result = command.execute()
            output = Path(directory) / 'media.srt'
            self.assertLoggedFalse('early finish is not a completed run', result)
            self.assertLoggedTrue('early finish recorded', command.stopped_early)
            self.assertLoggedFalse('command is not marked aborted', command.aborted)
            self.assertLoggedEqual('stop forwarded to coordinator', 1, self.coordinator.Abort.call_count)
            self.assertLoggedEqual('subtitles retained', self.subtitles, command.subtitles)
            self.assertLoggedEqual('partial save queued', 1, len(command.commands_to_queue))
            self.assertLoggedTrue('dependency evidence recorded', command.ffmpeg_available)
            save_command = command.commands_to_queue[0] if command.commands_to_queue else None
            self.assertLoggedIsInstance('follow-up writes the subtitles', save_command, SaveSubtitleFile)
            if isinstance(save_command, SaveSubtitleFile):
                save_command.execute()
            self.assertLoggedIn('partial subtitles written', 'Recovered text', output.read_text(encoding='utf-8-sig'))

    def test_early_finish_before_start_does_not_transcribe(self) -> None:
        """An early finish requested before the run starts produces no inference."""
        command = TranscribeMediaCommand(self.provider, 'media.wav', SettingsType(), save_transcription=True)
        command.FinishEarly()
        with patch('GuiSubtrans.Commands.TranscribeMediaCommand.TranscriptionCoordinator', return_value=self.coordinator):
            result = command.execute()
        self.assertLoggedFalse('early-finished run not successful', result)
        self.assertLoggedEqual('constructed coordinator is stopped', 1, self.coordinator.Abort.call_count)
        self.assertLoggedEqual('inference never begins', 0, self.coordinator.CreateTranscription.call_count)
        self.assertLoggedEqual('nothing to save', 0, len(command.commands_to_queue))

    def test_incomplete_run_queues_partial_save(self) -> None:
        """Partial results that finish without abort are still written."""
        self.coordinator.CreateTranscription.return_value = TranscriptionOutcome(
            TranscriptionStatus.INCOMPLETE, self.subtitles, transcribed_lines=1)
        command = TranscribeMediaCommand(self.provider, 'media.wav', SettingsType(), save_transcription=True)
        with patch('GuiSubtrans.Commands.TranscribeMediaCommand.TranscriptionCoordinator', return_value=self.coordinator):
            result = command.execute()
        self.assertLoggedFalse('incomplete command fails', result)
        self.assertLoggedEqual('one follow-up command queued', 1, len(command.commands_to_queue))
        self.assertLoggedIsInstance('follow-up writes the subtitles', command.commands_to_queue[0], SaveSubtitleFile)

    def test_saving_disabled_does_not_write(self) -> None:
        command = TranscribeMediaCommand(self.provider, 'media.wav', SettingsType())
        with patch('GuiSubtrans.Commands.TranscribeMediaCommand.TranscriptionCoordinator', return_value=self.coordinator):
            result = command.execute()
        self.assertLoggedTrue('transcription successful', result)
        self.assertLoggedEqual('no follow-up commands queued', 0, len(command.commands_to_queue))
        self.assertLoggedIsNone('no saved path', command.saved_path)

    def test_saves_selected_format_beside_media(self) -> None:
        """The queued follow-up command writes the transcription in the chosen format."""
        with TemporaryDirectory() as directory:
            media_path = Path(directory) / 'media.wav'
            command = TranscribeMediaCommand(self.provider, str(media_path), SettingsType(), save_transcription=True, output_format='VTT')
            with patch('GuiSubtrans.Commands.TranscribeMediaCommand.TranscriptionCoordinator', return_value=self.coordinator):
                result = command.execute()
            output = media_path.with_suffix('.vtt')
            self.assertLoggedTrue('transcription successful', result)
            self.assertLoggedEqual('saved path retained', str(output), command.saved_path)
            self.assertLoggedEqual('one follow-up command queued', 1, len(command.commands_to_queue))
            save_command = command.commands_to_queue[0]
            self.assertLoggedIsInstance('follow-up writes the subtitles', save_command, SaveSubtitleFile)
            if isinstance(save_command, SaveSubtitleFile):
                save_command.execute()
            self.assertLoggedIn('actual subtitle content written', 'Recovered text', output.read_text(encoding='utf-8-sig'))

    @skip_if_debugger_attached
    def test_save_failure_does_not_discard_completed_subtitles(self) -> None:
        """A failing save command leaves the transcription results untouched."""
        command = TranscribeMediaCommand(self.provider, 'media.wav', SettingsType(), save_transcription=True)
        with patch('GuiSubtrans.Commands.TranscribeMediaCommand.TranscriptionCoordinator', return_value=self.coordinator), \
                patch.object(self.subtitles, 'SaveOriginal', side_effect=OSError('disk full')) as save:
            result = command.execute()
            self.assertLoggedTrue('transcription remains successful', result)
            self.assertLoggedIs('completed subtitles retained', self.subtitles, command.subtitles)
            self.assertLoggedIsNotNone('save command queued', command.saved_path)
            save_command = command.commands_to_queue[0] if command.commands_to_queue else None
            self.assertLoggedIsInstance('follow-up writes the subtitles', save_command, SaveSubtitleFile)
            if isinstance(save_command, SaveSubtitleFile):
                with self.assertRaises(OSError):
                    save_command.execute()
        self.assertLoggedEqual('save attempted by follow-up command', 1, save.call_count)

    def test_dependency_capture_uses_already_loaded_torch(self) -> None:
        command = TranscribeMediaCommand(self.provider, 'media.wav', SettingsType())
        loaded_torch = Mock()
        with patch('GuiSubtrans.Commands.TranscribeMediaCommand.TranscriptionCoordinator', return_value=self.coordinator), \
                patch('GuiSubtrans.Commands.TranscribeMediaCommand.TranscriptionProvider.ResolveTorchDevice', return_value='cuda:0') as resolve, \
                patch.dict('sys.modules', {'torch': loaded_torch}):
            command.execute()
        self.assertLoggedIs('already-loaded torch passed to resolver', loaded_torch, resolve.call_args.args[0])
        self.assertLoggedTrue('ffmpeg evidence recorded', command.ffmpeg_available)
        self.assertLoggedEqual('device evidence recorded', 'cuda:0', command.torch_device)
