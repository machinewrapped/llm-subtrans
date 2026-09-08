"""Focused lifecycle checks for the transcription dialog."""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from GuiSubtrans.Widgets.TranscriptionDialog import TranscriptionDialog
from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Options import Options
from PySubtrans.Transcription.TranscriptionCoordinator import TranscriptionStatus


class TestTranscriptionDialogLifecycle(LoggedTestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        with patch.object(TranscriptionDialog, "_refresh_providers"):
            self.dialog = TranscriptionDialog(Options())

    def tearDown(self):
        self.dialog.close()
        self.dialog.deleteLater()
        self.application.processEvents()

    def test_reject_aborts_active_worker_without_dismissing(self):
        """Close/Escape requests abort while preserving the live dialog."""
        class Coordinator:
            status = TranscriptionStatus.IDLE
            aborted = False

            def Abort(self):
                self.aborted = True

        class Thread:
            def isRunning(self):
                return True

        coordinator = Coordinator()
        self.dialog.coordinator = coordinator
        self.dialog.thread = Thread()
        self.dialog._worker_active = True
        self.dialog.reject()
        self.assertLoggedTrue("coordinator abort requested", coordinator.aborted)
        self.assertLoggedEqual("dialog remains open while worker stops", 0, self.dialog.result())

    def test_clean_completion_accepts_only_after_thread_finished(self):
        """A clean run waits for QThread.finished before accepting."""
        coordinator = type("Coordinator", (), {
            "status": TranscriptionStatus.COMPLETED,
            "aborted": False,
        })()
        project = type("Project", (), {
            "subtitles": type("Subtitles", (), {"linecount": 1})(),
        })()
        self.dialog.coordinator = coordinator
        self.dialog._save_transcription = lambda unused_project: None
        self.dialog._record_dependency_evidence = lambda ffmpeg_available: None
        self.dialog._record_torch_device = lambda: None
        with patch.object(self.dialog, "_show_results"):
            self.dialog._on_finished(project)
        self.assertLoggedEqual("accept deferred until thread stop", 0, self.dialog.result())
        self.dialog._on_worker_thread_finished()
        self.assertLoggedEqual("clean result accepted after thread stop", 1, self.dialog.result())

    def test_incomplete_completion_stays_recoverable(self):
        """Incomplete results remain available for explicit Open as Project."""
        coordinator = type("Coordinator", (), {
            "status": TranscriptionStatus.INCOMPLETE,
            "aborted": False,
        })()
        project = type("Project", (), {
            "subtitles": type("Subtitles", (), {"linecount": 2})(),
        })()
        self.dialog.coordinator = coordinator
        self.dialog._save_transcription = lambda unused_project: None
        self.dialog._record_dependency_evidence = lambda ffmpeg_available: None
        self.dialog._record_torch_device = lambda: None
        with patch.object(self.dialog, "_show_results"):
            self.dialog._on_finished(project)
        self.assertLoggedEqual("incomplete result remains open", 0, self.dialog.result())
        self.assertLoggedIsNotNone("partial project is recoverable", self.dialog.project)


if __name__ == "__main__":
    unittest.main()
