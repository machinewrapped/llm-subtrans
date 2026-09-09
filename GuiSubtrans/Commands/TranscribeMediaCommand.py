import logging
import sys
from copy import copy, deepcopy
from threading import RLock

from PySide6.QtCore import Signal

from GuiSubtrans.Command import Command
from GuiSubtrans.Commands.SaveSubtitleFile import SaveSubtitleFile
from PySubtrans.Helpers import GetOutputPath
from PySubtrans.Helpers.Localization import _
from PySubtrans.Options import Options
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleProject import SubtitleProject
from PySubtrans.Transcription.TranscriptionCoordinator import TranscriptionCoordinator, TranscriptionStatus
from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider


class TranscribeMediaCommand(Command):
    """Run a media transcription as a project-opening command."""

    progressed = Signal(int, int, str)
    segmented = Signal(object)

    def __init__(self, provider : TranscriptionProvider, media_path : str,
                 settings : SettingsType, options : Options|None = None,
                 save_transcription : bool = False, output_format : str = "srt") -> None:
        super().__init__()
        self.provider : TranscriptionProvider = copy(provider)
        self.provider.settings = SettingsType(deepcopy(provider.settings))
        self.media_path : str = media_path
        self.settings : SettingsType = SettingsType(deepcopy(settings))
        self.options : Options = Options(options)
        self.save_transcription : bool = save_transcription
        self.output_format : str = output_format.casefold()
        self.coordinator : TranscriptionCoordinator|None = None
        self.project : SubtitleProject|None = None
        self.status : TranscriptionStatus = TranscriptionStatus.IDLE
        self.error : str|None = None
        self.saved_path : str|None = None
        self.stopped_early : bool = False
        self.ffmpeg_available : bool = False
        self.torch_device : str|None = None
        self._coordinator_lock : RLock = RLock()
        self.is_blocking = True
        self.can_undo = False
        # The result is handed over via signals, so the command never enters
        # the undo stack; on success the previous project's undo history is
        # cleared because the project boundary was crossed.
        self.skip_undo = True
        self.mark_project_dirty = False

    def execute(self) -> bool:
        """Transcribe media and retain any usable partial project."""
        try:
            if self.aborted:
                return False

            coordinator = self._create_coordinator()
            if coordinator is None:
                return False

            self._run_transcription(coordinator)

            if not self.aborted:
                self._record_runtime_evidence()
                self._queue_project_save()

            # An early finish ends as an orderly, unsuccessful command so the
            # queue still runs its follow-up commands (the partial results save).
            return self.status is TranscriptionStatus.COMPLETED and not self.aborted

        except Exception as error:
            self._recover_partial_result(error)
            return False

    def on_abort(self) -> None:
        """Forward cancellation, including cancellation during setup."""
        with self._coordinator_lock:
            coordinator = self.coordinator
        if coordinator is not None:
            coordinator.Abort()

    def FinishEarly(self) -> None:
        """
        Request an early finish: stop transcription without cancelling the
        command, so its follow-up commands (the partial results save) still
        run. The result is retained but not treated as a completed run.
        """
        self.stopped_early = True
        with self._coordinator_lock:
            coordinator = self.coordinator
        if coordinator is not None:
            coordinator.Abort()

    def _create_coordinator(self) -> TranscriptionCoordinator|None:
        """Create the coordinator, honouring cancellation during setup."""
        coordinator = TranscriptionCoordinator(self.provider, self.settings)

        with self._coordinator_lock:
            self.coordinator = coordinator
            stop_requested = self.aborted or self.stopped_early

        if stop_requested:
            coordinator.Abort()
            return None

        return coordinator

    def _run_transcription(self, coordinator : TranscriptionCoordinator) -> None:
        """Transcribe the media, streaming progress and segments to the UI."""
        self.project = coordinator.CreateTranscriptionProject(
            self.media_path, self.options,
            lambda done, total, span: self.progressed.emit(done, total, span),
            lambda segment: self.segmented.emit(segment))

        self.status = coordinator.status
        if coordinator.last_error is not None:
            self.error = str(coordinator.last_error)

    def _record_runtime_evidence(self) -> None:
        """Record dependency facts proven by a real run for future sessions."""
        self.ffmpeg_available = True
        self.torch_device = self._resolved_torch_device()

    def _queue_project_save(self) -> None:
        """Queue the subtitle file write as a follow-up command."""
        project = self.project
        if project is None or project.subtitles is None or not self.save_transcription:
            return

        outputpath = GetOutputPath(self.media_path, None, f".{self.output_format}")
        if not outputpath:
            return

        # The follow-up command performs the write; a failure there is logged
        # by the queue without discarding the transcription results.
        self.saved_path = outputpath
        self.commands_to_queue.append(SaveSubtitleFile(outputpath, project))

    def _recover_partial_result(self, error : Exception) -> None:
        """Keep any subtitles recovered before a failure so billed work isn't lost."""
        self.error = str(error)
        self.status = TranscriptionStatus.FAILED

        with self._coordinator_lock:
            partial_subtitles = self.coordinator.partial_subtitles if self.coordinator else None
        if partial_subtitles is not None:
            self.project = SubtitleProject(persistent=False)
            self.project.subtitles = partial_subtitles
            self.project.projectfile = self.project.GetProjectFilepath(self.media_path)

        logging.error(_("Transcription failed: {error}").format(error=error))

    @staticmethod
    def _resolved_torch_device() -> str|None:
        """Read already-loaded torch state without importing torch."""
        device = TranscriptionProvider.ResolveTorchDevice(sys.modules.get('torch'))
        return None if device == "Unknown" else device
