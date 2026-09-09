from PySide6.QtCore import QObject, Signal, Slot

from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider


class TranscriptionProviderLoader(QObject):
    """
    Resolves transcription provider names off the GUI thread.

    The first import pulls heavy optional SDKs (qwen_asr takes ~10s),
    so a synchronous load would stall the dialog on first open.
    Shared by TranscriptionDialog and SettingsDialog.
    """
    loaded = Signal(list)
    failed = Signal(str)

    @Slot()
    def run(self) -> None:
        """Resolve provider names, emitting them back to the caller."""
        try:
            names = sorted(TranscriptionProvider.get_providers())
            self.loaded.emit(names)
        except Exception as e:
            self.failed.emit(str(e))
