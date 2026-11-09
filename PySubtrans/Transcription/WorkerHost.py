"""Synchronous JSON-line transport for isolated local transcription runtimes."""

import atexit
import json
import logging
import subprocess
from collections.abc import Callable
from pathlib import Path
from threading import RLock, Thread
from typing import Any

import regex

from PySubtrans.Helpers.Localization import _
from PySubtrans.SubtitleError import SubtitleError


class WorkerError(SubtitleError):
    """A worker transport, protocol, or runtime failure."""

    def __init__(self, message : str, error_type : str = 'WorkerError'):
        super().__init__(message)
        self.error_type : str = error_type


def EncodeMessage(message : dict[str, Any]) -> str:
    """Encode one complete JSON line, rejecting messages without a known type."""
    ValidateMessage(message)

    try:
        return json.dumps(message, ensure_ascii=True, allow_nan=False) + '\n'
    except (TypeError, ValueError) as error:
        raise WorkerError(_("Unable to encode worker message: {}").format(error)) from error


def DecodeMessage(line : str) -> dict[str, Any]:
    """Decode and validate a single protocol message."""
    if not line.endswith('\n'):
        raise WorkerError(_("Incomplete worker message"))

    try:
        message = json.loads(line, parse_constant=_RejectConstant)
    except (ValueError, TypeError) as error:
        raise WorkerError(_("Malformed worker message: {}").format(error)) from error

    ValidateMessage(message)
    return message


def _RejectConstant(value : str) -> None:
    """Reject non-finite JavaScript constants which are not valid JSON."""
    raise ValueError(value)


def ValidateMessage(message : Any) -> None:
    """Validate the envelope; runtime-specific payloads belong to the client."""
    if not isinstance(message, dict) or message.get('type') not in (
            'load', 'ready', 'transcribe', 'segment', 'result', 'error', 'shutdown'):
        raise WorkerError(_("Unexpected worker message shape"))

    if message['type'] == 'error' and not all(isinstance(message.get(key), str) for key in ('error_type', 'message')):
        raise WorkerError(_("Malformed worker error"))


# A progress bar update, such as 'Loading weights:  65%|######5   | 444/683 [...]'.
# The bar redraws itself with carriage returns, which the text-mode stream reads as separate lines.
_PROGRESS_BAR = regex.compile(r'^\s*(?:(?P<label>[^|]*?):\s*)?(?P<percent>\d{1,3})%\|')


def ProgressBarStatus(line : str) -> tuple[str, bool]|None:
    """The status text for a progress bar update, with whether the bar is complete, or None if the line is not one."""
    match = _PROGRESS_BAR.match(line)
    if match is None:
        return None

    label = (match.group('label') or '').strip()
    percent = int(match.group('percent'))
    text = f"{label}: {percent}%" if label else f"{percent}%"
    return text, percent >= 100


def WorkerScriptPath(name : str) -> Path:
    """Find scripts beside this module, including PyInstaller's data directory."""
    return Path(__file__).resolve().parent / 'Workers' / name


class WorkerHost:
    """Own one runtime process, serializing requests while allowing immediate abort.

    A runtime stays loaded across requests until shutdown or abort.
    Abort never takes the request lock, so a blocked read can be interrupted.
    """

    _LOG_LEVELS : dict[str, int] = {
        'DEBUG': logging.DEBUG,
        'INFO': logging.INFO,
        'WARNING': logging.WARNING,
        'ERROR': logging.ERROR,
        'CRITICAL': logging.CRITICAL,
    }

    def __init__(self, python : str, script : Path):
        self._python : str = python
        self._script : Path = script
        self._process : subprocess.Popen[str]|None = None
        self._request_lock = RLock()
        self._state_lock = RLock()
        self._stderr_thread : Thread|None = None
        self._aborted : bool = False
        self._on_progress : Callable[[str], None]|None = None
        atexit.register(self.Abort)

    @property
    def running(self) -> bool:
        """Whether the runtime can accept another request."""
        with self._state_lock:
            return self._process is not None and self._process.poll() is None and not self._aborted

    def Start(self) -> None:
        """Launch the environment's interpreter without application import paths."""
        with self._state_lock:
            if self._aborted:
                raise WorkerError(_("Transcription worker was aborted"))
            if self._process is not None:
                return

            try:
                self._process = subprocess.Popen(
                    [self._python, '-I', str(self._script)],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, encoding='utf-8', errors='replace', bufsize=1,
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
                )
            except OSError as error:
                raise WorkerError(_("Unable to start transcription worker: {}").format(error)) from error

            self._stderr_thread = Thread(target=self._ForwardStderr, args=(self._process,), daemon=True)
            self._stderr_thread.start()

    def Request(self, message : dict[str, Any], expected : str,
                on_segment : Callable[[dict[str, Any]], None]|None = None,
                on_progress : Callable[[str], None]|None = None) -> dict[str, Any]:
        """
        Send a request and wait for exactly one response or an error.
        Segment messages sent while the request runs are passed to on_segment.
        Progress bars the worker's libraries draw while it runs are passed to on_progress as status text, from the stderr thread.
        """
        encoded = EncodeMessage(message)

        with self._request_lock:
            self.Start()
            process = self._process
            assert process is not None and process.stdin is not None and process.stdout is not None
            self._on_progress = on_progress

            try:
                process.stdin.write(encoded)
                process.stdin.flush()

                response = self._ReadMessage(process)
                while response['type'] == 'segment':
                    if on_segment is not None:
                        on_segment(response)
                    response = self._ReadMessage(process)

                if response['type'] == 'error':
                    raise WorkerError(_("Transcription worker failed ({}): {}").format(
                        response['error_type'], response['message']), response['error_type'])
                if response['type'] != expected:
                    raise WorkerError(_("Unexpected transcription worker response: {}").format(response['type']))

                return response
            except (OSError, ValueError) as error:
                self.Abort()
                raise WorkerError(_("Transcription worker communication failed: {}").format(error)) from error
            except Exception:
                # The worker may still be mid-request, so its later output would answer the next request
                self.Abort()
                raise
            finally:
                self._on_progress = None

    def Shutdown(self) -> None:
        """Ask an idle worker to exit, with bounded termination as a fallback."""
        with self._request_lock:
            process = self._process
            if process is not None and process.poll() is None and process.stdin is not None:
                try:
                    process.stdin.write(EncodeMessage({'type': 'shutdown'}))
                    process.stdin.flush()
                    process.wait(timeout=5)
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    pass

            self.Abort()

    def Abort(self) -> None:
        """Terminate inference and reap the process, including on application exit."""
        with self._state_lock:
            self._aborted = True
            process = self._process
            if process is not None:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()

                # The reader owns stdout while a request is active.
                # Process exit unblocks that read before the stream can be closed.
                for stream in (process.stdin, process.stdout):
                    if stream is not None:
                        try:
                            stream.close()
                        except OSError:
                            # A broken pipe may still have buffered input to flush.
                            pass

            atexit.unregister(self.Abort)

    @staticmethod
    def _ReadMessage(process : subprocess.Popen[str]) -> dict[str, Any]:
        """Read the next protocol message from the worker."""
        assert process.stdout is not None
        line = process.stdout.readline()
        if not line:
            raise WorkerError(_("Transcription worker exited before replying (exit code {})").format(process.poll()))

        return DecodeMessage(line)

    def _ForwardStderr(self, process : subprocess.Popen[str]) -> None:
        """Drain diagnostics concurrently so library output cannot stall inference."""
        assert process.stderr is not None
        with process.stderr:
            for line in process.stderr:
                if not line.strip():
                    continue

                level = logging.INFO
                message = line.rstrip()

                # Progress bars go to the request's status rather than the log, apart from their completion
                progress = ProgressBarStatus(message)
                if progress is not None:
                    text, complete = progress
                    on_progress = self._on_progress
                    if on_progress is not None:
                        on_progress(text)
                    if complete:
                        logging.debug("Transcription worker: %s", text)
                    continue

                # Only worker log records carry this prefix.
                # Unmarked SDK output and traceback continuations retain INFO.
                if message.startswith('SUBTRANS_WORKER '):
                    level_name, separator, detail = message[len('SUBTRANS_WORKER '):].partition(' ')
                    if separator and level_name in self._LOG_LEVELS:
                        level = self._LOG_LEVELS[level_name]
                        message = detail

                logging.log(level, "Transcription worker: %s", message)
