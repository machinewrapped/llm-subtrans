"""Dialog that waits while the user signs in with ChatGPT in their web browser."""

import logging
import threading

from PySide6.QtCore import QObject, QThreadPool, Signal, Slot
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QMessageBox, QVBoxLayout, QWidget

from PySubtrans.Auth.ChatGPTAuth import MANAGE_USAGE_URL, ChatGPTAuth, ChatGPTAuthError
from PySubtrans.Helpers.Localization import _

# Keep running workers referenced until they finish, so a closed dialog cannot leave a worker to be garbage collected
_active_workers : set['_SignInWorker'] = set()


class _SignInWorker(QObject):
    """
    Runs the blocking browser sign-in on the global thread pool.
    The worker has GUI-thread affinity, so its signals are delivered on the GUI thread.
    """
    succeeded = Signal()
    failed = Signal(str)
    _finished = Signal()

    def __init__(self, auth : ChatGPTAuth):
        # Unparented, so closing the dialog cannot delete the worker while sign-in is in progress
        super().__init__()
        self.auth = auth
        self.cancel_event = threading.Event()
        self._finished.connect(self._on_finished)

    def start(self) -> None:
        _active_workers.add(self)
        QThreadPool.globalInstance().start(self._run)

    def _run(self) -> None:
        try:
            self.auth.SignIn(self.cancel_event)
            self.succeeded.emit()

        except (ChatGPTAuthError, OSError) as e:
            self.failed.emit(str(e))

        finally:
            self._finished.emit()

    @Slot()
    def _on_finished(self) -> None:
        _active_workers.discard(self)


class ChatGPTSignInDialog(QDialog):
    """
    Starts the sign-in with ChatGPT and waits for the user to complete it in the browser.
    Shows a one-time message on the first successful sign-in.
    """
    def __init__(self, auth : ChatGPTAuth, parent : QWidget|None = None):
        super().__init__(parent)
        self.auth = auth
        self._cancelled : bool = False

        self.setWindowTitle(_("Sign in with ChatGPT"))
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(_("Complete sign-in in your web browser, then return here."), self))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._worker = _SignInWorker(auth)
        self._worker.succeeded.connect(self._on_succeeded)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def reject(self) -> None:
        """Cancel the sign-in attempt, which stops the loopback listener."""
        self._cancelled = True
        self._worker.cancel_event.set()
        super().reject()

    @Slot()
    def _on_succeeded(self) -> None:
        if self._cancelled:
            return

        self._show_welcome()
        self.accept()

    @Slot(str)
    def _on_failed(self, message : str) -> None:
        if self._cancelled:
            return

        logging.warning(message)
        QMessageBox.warning(self, _("Sign in with ChatGPT"), message)
        super().reject()

    def _show_welcome(self) -> None:
        """Explain plan usage the first time the user signs in."""
        if self.auth.welcome_shown:
            return

        message = QMessageBox(self)
        message.setWindowTitle(_("Sign in with ChatGPT"))
        message.setText(_("You're using your ChatGPT plan"))
        message.setInformativeText(_("Translation requests with OpenAI will use your ChatGPT plan's usage allowance, not a separately billed API key. You can manage usage in your ChatGPT settings: {url}").format(url=MANAGE_USAGE_URL))
        message.addButton(_("Got it"), QMessageBox.ButtonRole.AcceptRole)
        message.exec()

        self.auth.MarkWelcomeShown()
