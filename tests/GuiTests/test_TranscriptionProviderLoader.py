"""Exercise off-thread transcription provider loading."""
import logging
import threading
import time
from threading import Event
from unittest.mock import patch

from tests.GuiTestSupport import ConfigureOffscreenPlatform

ConfigureOffscreenPlatform()

from PySide6.QtWidgets import QApplication

from GuiSubtrans.Widgets.TranscriptionProviderLoader import TranscriptionProviderLoader
from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider


class TestTranscriptionProviderLoader(LoggedTestCase):
    application : QApplication

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        existing = QApplication.instance()
        cls.application = existing if isinstance(existing, QApplication) else QApplication([])

    def _await(self, loader : TranscriptionProviderLoader) -> None:
        """Pump events until the loader has reported back."""
        deadline = time.monotonic() + 2
        while loader.running and time.monotonic() < deadline:
            self.application.processEvents()
            time.sleep(0.01)

    def test_names_are_resolved_off_the_gui_thread(self) -> None:
        """Provider names are sorted and delivered on the GUI thread, with the lookup on a worker."""
        lookup_threads : list[threading.Thread] = []
        received : list[list] = []

        def get_providers() -> list[str]:
            lookup_threads.append(threading.current_thread())
            return ['Beta', 'Alpha']

        with patch.object(TranscriptionProvider, 'get_providers', side_effect=get_providers):
            loader = TranscriptionProviderLoader()
            loader.loaded.connect(received.append)
            loader.start()
            self._await(loader)

        self.assertLoggedFalse('loader finished', loader.running)
        self.assertLoggedEqual('names delivered sorted', [['Alpha', 'Beta']], received)
        self.assertLoggedEqual('one lookup', 1, len(lookup_threads))
        self.assertLoggedFalse('lookup ran off the GUI thread', lookup_threads[0] is threading.main_thread())

    def test_stopped_loader_discards_its_result(self) -> None:
        """A loader stopped while the import is in flight reports nothing."""
        started = Event()
        release = Event()
        received : list[list] = []

        def get_providers() -> list[str]:
            started.set()
            release.wait(2)
            return ['Alpha']

        with patch.object(TranscriptionProvider, 'get_providers', side_effect=get_providers):
            loader = TranscriptionProviderLoader()
            loader.loaded.connect(received.append)
            loader.start()
            self.assertLoggedTrue('lookup started', started.wait(2))

            loader.stop()
            release.set()
            self._await(loader)

        self.assertLoggedFalse('loader finished', loader.running)
        self.assertLoggedEqual('result discarded', [], received)

    def test_failure_is_reported(self) -> None:
        """An import failure is reported through the failed signal."""
        received : list[str] = []

        with patch.object(TranscriptionProvider, 'get_providers', side_effect=ImportError("missing")):
            loader = TranscriptionProviderLoader()
            loader.failed.connect(received.append)
            loader.start()
            self._await(loader)

        self.assertLoggedEqual('failure reported', 1, len(received))


if __name__ == '__main__':
    import unittest
    logging.basicConfig(level=logging.INFO)
    unittest.main()
