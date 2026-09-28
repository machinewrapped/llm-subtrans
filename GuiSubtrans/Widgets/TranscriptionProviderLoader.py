from PySide6.QtCore import QObject, QThreadPool, Signal, Slot

from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider

# Keep running loaders referenced until their work finishes, so a loader
# abandoned by a closed dialog cannot be garbage collected mid-import.
_active_loaders : set['TranscriptionProviderLoader'] = set()


class TranscriptionProviderLoader(QObject):
    """
    Resolves transcription provider names off the GUI thread.

    The first import pulls heavy optional SDKs (qwen_asr takes ~10s),
    so a synchronous load would stall the dialog on first open.
    The import runs on the global thread pool, so a dialog can close without waiting for it.
    The loader object has GUI-thread affinity, so results are reported and the loader is deleted there.
    Shared by TranscriptionDialog and SettingsDialog.
    """
    loaded = Signal(list)
    failed = Signal(str)
    _completed = Signal(list, str)

    def __init__(self):
        # Unparented, so a closing dialog cannot delete the loader while the import is in flight
        super().__init__()
        self._running : bool = False
        self._stopped : bool = False

        # Emitted from the pool thread, so this is delivered on the GUI thread
        self._completed.connect(self._on_completed)

    @property
    def running(self) -> bool:
        """Whether the load is still in progress."""
        return self._running

    def start(self) -> None:
        """Run the load on a worker thread."""
        if self._running:
            return

        self._running = True
        _active_loaders.add(self)
        QThreadPool.globalInstance().start(self._run_in_pool)

    def stop(self) -> None:
        """Discard the result when it arrives, since an import cannot be interrupted."""
        self._stopped = True

    def _run_in_pool(self) -> None:
        """Resolve provider names on the worker thread, handing the outcome to the GUI thread."""
        try:
            names = sorted(TranscriptionProvider.get_providers())
            self._completed.emit(names, "")
        except Exception as e:
            self._completed.emit([], str(e) or type(e).__name__)

    @Slot(list, str)
    def _on_completed(self, names : list, error : str) -> None:
        """Report the outcome unless stopped, then release the loader."""
        self._running = False
        _active_loaders.discard(self)
        self.deleteLater()

        # Checked here rather than on the worker, so stop() on the GUI thread cannot race the result
        if self._stopped:
            return

        if error:
            self.failed.emit(error)
        else:
            self.loaded.emit(names)
