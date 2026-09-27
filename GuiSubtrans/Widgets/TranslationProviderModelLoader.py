from PySide6.QtCore import QObject, QThreadPool, Signal, Slot

from PySubtrans.TranslationProvider import TranslationProvider

# Keep running loaders referenced until their work finishes, so a superseded
# loader cannot be garbage collected while its worker is still running.
_active_loaders : set['TranslationProviderModelLoader'] = set()


class TranslationProviderModelLoader(QObject):
    """
    Resolves a translation provider's model list off the GUI thread.

    The lookup runs on the global thread pool, so a slow request never blocks the GUI.
    The loader object has GUI-thread affinity, so its completion handling and deletion happen there.
    A dedicated QThread that deleted itself on finish raced PySide's wrapper teardown and crashed.
    The provider's name is reported back so late results for a superseded provider can be ignored.
    The outcome is recorded on the provider's ModelList, so a failure keeps the persisted model selectable.
    """
    loaded = Signal(str)
    failed = Signal(str, str)
    _finished = Signal()

    def __init__(self, provider : TranslationProvider):
        # Unparented, so a closing owner cannot delete the loader while the lookup is in flight
        super().__init__()
        self.provider = provider
        self._running : bool = False
        self._request : int = 0

        # Emitted from the pool thread, so this is delivered on the GUI thread
        self._finished.connect(self._on_finished)

    @property
    def running(self) -> bool:
        """Whether the load is still in progress."""
        return self._running

    def start(self) -> None:
        """Run the load on a worker thread."""
        if self._running:
            return

        self._request = self.provider.model_list.BeginLoad()
        self._running = True

        _active_loaders.add(self)
        QThreadPool.globalInstance().start(self._run_in_pool)

    def stop(self) -> None:
        """Release the loader without blocking the GUI thread.
        The worker finishes on its own and its result is discarded, since a request cannot be interrupted.
        """
        # Cancelling makes the request stale, so the worker cannot record its result
        self.provider.model_list.Cancel()

    @Slot()
    def run(self) -> None:
        """Resolve the model list on the provider, emitting the outcome back to the caller."""
        provider = self.provider

        if not provider.model_list.Resolve(self._request):
            # A superseded or cancelled lookup has nothing to report
            return

        if provider.model_list.resolved:
            self.loaded.emit(provider.name)
        else:
            self.failed.emit(provider.name, provider.model_list.error or "")

    def _run_in_pool(self) -> None:
        """Pool entry point, which always reports completion to the GUI thread."""
        try:
            self.run()
        finally:
            self._finished.emit()

    @Slot()
    def _on_finished(self) -> None:
        """Release the loader on the GUI thread once the worker is done with it."""
        self._running = False
        _active_loaders.discard(self)
        self.deleteLater()
