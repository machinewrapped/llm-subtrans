"""Exercise transport and process lifetime with memory-only process doubles."""

import io
import json
import logging
import subprocess
from pathlib import Path
from threading import Event, Thread
from unittest.mock import Mock, patch

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Helpers.Tests import log_input_expected_error, skip_if_debugger_attached
from PySubtrans.Transcription.WorkerHost import DecodeMessage, EncodeMessage, WorkerError, WorkerHost, WorkerScriptPath


class TestWorkerProtocol(LoggedTestCase):
    """Every channel message occupies exactly one JSON line."""

    def test_round_trip(self) -> None:
        """Unicode, embedded newlines and nested results survive encoding."""
        for message in (
                {'type': 'load', 'checkpoint': 'model'}, {'type': 'ready', 'device': 'cpu'},
                {'type': 'transcribe', 'path': 'a.wav'},
                {'type': 'result', 'text': '\u4f60\u597d\nworld', 'time_stamps': [{'start_time': 0.5}]},
                {'type': 'error', 'error_type': 'ValueError', 'message': 'first\nsecond'},
                {'type': 'shutdown'}):
            encoded = EncodeMessage(message)
            self.assertLoggedEqual('one complete protocol line', 1, encoded.count('\n'))
            self.assertLoggedEqual('message round trip', message, DecodeMessage(encoded))

    @skip_if_debugger_attached
    def test_malformed_messages(self) -> None:
        """Invalid JSON, envelopes and incomplete errors fail predictably."""
        for line in ('', 'library chatter\n', '{}\n', '[]\n', 'null\n', '42\n', '{"type":"other"}\n',
                     '{"type":[]}\n', '{"type":"error","message":"failed"}\n', '{}\n{}\n',
                     '{"type":"result","value":NaN}\n', '{"type":"result","value":Infinity}\n',
                     '{"type":"ready"}'):
            with self.subTest(line=line), self.assertRaises(WorkerError) as raised:
                DecodeMessage(line)
            log_input_expected_error(line, WorkerError, raised.exception)

    @skip_if_debugger_attached
    def test_unencodable_payload(self) -> None:
        """Non-JSON values and non-finite numbers cannot enter the channel."""
        for payload in (object(), float('nan')):
            with self.assertRaises(WorkerError):
                EncodeMessage({'type': 'result', 'value': payload})

    def test_script_path_does_not_depend_on_cwd(self) -> None:
        """Source and frozen package paths resolve relative to the module."""
        with patch('PySubtrans.Transcription.WorkerHost.__file__', '/bundle/PySubtrans/Transcription/WorkerHost.py'):
            path = WorkerScriptPath('qwen_worker.py')
        self.assertLoggedEqual('worker data beside module', Path('/bundle/PySubtrans/Transcription/Workers/qwen_worker.py').resolve(), path)


class TestWorkerHost(LoggedTestCase):
    """Use streams and mocks instead of spawning a real process."""

    def setUp(self) -> None:
        super().setUp()
        self.process = Mock()
        self.process.stdin = io.StringIO()
        self.process.stdout = io.StringIO('{"type":"ready"}\n')
        self.process.stderr = io.StringIO()
        self.process.poll.return_value = None
        self.host = WorkerHost('environment-python', Path('worker.py'))
        self.addCleanup(self.host.Abort)
        self.popen = patch('PySubtrans.Transcription.WorkerHost.subprocess.Popen', return_value=self.process)
        self.start = self.popen.start()
        self.addCleanup(self.popen.stop)

    def test_launch_and_request(self) -> None:
        """Isolation and UTF-8 pipes are used, and a request receives its reply."""
        message = {'type': 'load', 'checkpoint': 'model'}
        response = self.host.Request(message, 'ready')
        self.assertLoggedEqual('ready reply', {'type': 'ready'}, response)
        self.assertLoggedEqual('request encoded', message, json.loads(self.process.stdin.getvalue()))
        args, kwargs = self.start.call_args
        self.assertLoggedEqual('isolated invocation', ['environment-python', '-I', 'worker.py'], args[0])
        self.assertLoggedEqual('UTF-8 channel', 'utf-8', kwargs['encoding'])
        self.assertLoggedEqual('stderr is piped', subprocess.PIPE, kwargs['stderr'])

    @skip_if_debugger_attached
    def test_early_exit(self) -> None:
        """EOF fails the request and reaps the worker."""
        self.process.stdout = io.StringIO()
        self.process.poll.return_value = 7
        with self.assertRaises(WorkerError) as raised:
            self.host.Request({'type': 'load'}, 'ready')
        log_input_expected_error('EOF', WorkerError, raised.exception)
        self.assertLoggedFalse('worker unavailable', self.host.running)
        self.assertLoggedTrue('input closed', self.process.stdin.closed)

    @skip_if_debugger_attached
    def test_bad_reply_terminates_worker(self) -> None:
        """Malformed or out-of-sequence responses poison the channel."""
        for response in ('not json\n', '{"type":"result"}\n', '{"type":"error"}\n'):
            host = WorkerHost('python', Path('worker.py'))
            self.process.stdout = io.StringIO(response)
            self.process.stdin = io.StringIO()
            self.process.stderr = io.StringIO()
            with self.assertRaises(WorkerError):
                host.Request({'type': 'load'}, 'ready')
            self.assertLoggedFalse('bad channel retired', host.running)

    @skip_if_debugger_attached
    def test_runtime_error_preserves_type(self) -> None:
        """SDK errors are returned as structured worker failures."""
        self.process.stdout = io.StringIO(EncodeMessage({'type': 'error', 'error_type': 'ImportError', 'message': 'missing SDK'}))
        with self.assertRaises(WorkerError) as raised:
            self.host.Request({'type': 'load'}, 'ready')
        self.assertLoggedEqual('SDK exception classification', 'ImportError', raised.exception.error_type)

    def test_stderr_forwarded(self) -> None:
        """Diagnostics are logged separately from result decoding."""
        self.process.stderr = io.StringIO('model diagnostics\n')
        with self.assertLogs(level='INFO') as logs:
            self.host.Start()
            thread = self.host._stderr_thread
            assert thread is not None
            thread.join(timeout=2)
        self.assertLoggedEqual('diagnostic records', 1, len(logs.records))

    def test_stderr_log_levels(self) -> None:
        """Worker levels survive forwarding while unmarked library output stays at INFO."""
        for line, expected in (
                ('SUBTRANS_WORKER DEBUG diagnostic\n', logging.DEBUG),
                ('SUBTRANS_WORKER INFO model loaded\n', logging.INFO),
                ('SUBTRANS_WORKER WARNING alignment fallback\n', logging.WARNING),
                ('SUBTRANS_WORKER ERROR runtime failure\n', logging.ERROR),
                ('SUBTRANS_WORKER CRITICAL fatal failure\n', logging.CRITICAL),
                ('library output\n', logging.INFO),
                ('Traceback (most recent call last):\n', logging.INFO),
                ('  File "worker.py", line 1\n', logging.INFO),
                ('SUBTRANS_WORKER UNKNOWN diagnostic\n', logging.INFO)):
            with self.subTest(expected=expected):
                self.process.stderr = io.StringIO(line)
                with self.assertLogs(level=expected) as logs:
                    self.host._ForwardStderr(self.process)

                self.assertLoggedEqual('forwarded record count', 1, len(logs.records))
                self.assertLoggedEqual('forwarded log level', expected, logs.records[0].levelno)

    def test_abort(self) -> None:
        """Abort terminates and waits without sending another protocol request."""
        self.host.Start()
        self.host.Abort()
        self.assertLoggedEqual('terminate called', 1, self.process.terminate.call_count)
        self.assertLoggedEqual('process reaped', 1, self.process.wait.call_count)
        self.assertLoggedFalse('worker retired', self.host.running)

    @skip_if_debugger_attached
    def test_abort_before_start(self) -> None:
        """An aborted host can never create a process on a later request."""
        self.host.Abort()
        with self.assertRaises(WorkerError):
            self.host.Request({'type': 'load'}, 'ready')
        self.assertLoggedEqual('no process created', 0, self.start.call_count)

    @skip_if_debugger_attached
    def test_start_failure(self) -> None:
        """An inaccessible interpreter becomes an application-compatible failure."""
        self.start.side_effect = OSError('cannot start')
        with self.assertRaises(WorkerError):
            self.host.Request({'type': 'load'}, 'ready')
        self.assertLoggedFalse('no worker running', self.host.running)

    @skip_if_debugger_attached
    def test_abort_during_request(self) -> None:
        """A blocked response read never prevents abort from reaching the process."""
        reading = Event()
        terminated = Event()
        failures : list[Exception] = []

        def ReadLine() -> str:
            reading.set()
            terminated.wait(timeout=2)
            return ''

        def Request() -> None:
            try:
                self.host.Request({'type': 'load'}, 'ready')
            except WorkerError as error:
                failures.append(error)

        self.process.stdout = Mock(readline=ReadLine)
        self.process.terminate.side_effect = terminated.set
        request = Thread(target=Request)
        request.start()
        self.assertLoggedTrue('request waiting', reading.wait(timeout=2))
        self.host.Abort()
        request.join(timeout=2)
        self.assertLoggedFalse('request completed', request.is_alive())
        self.assertLoggedEqual('request interrupted', 1, len(failures))

    @skip_if_debugger_attached
    def test_abort_kills_unresponsive_process(self) -> None:
        """A worker which ignores termination is killed and reaped."""
        self.process.wait.side_effect = [subprocess.TimeoutExpired('worker', 5), 0]
        self.host.Start()
        self.host.Abort()
        self.process.poll.return_value = 0
        self.assertLoggedEqual('kill called', 1, self.process.kill.call_count)

    def test_shutdown(self) -> None:
        """Shutdown sends the protocol command before closing the pipes."""
        self.host.Start()
        sent : list[str] = []
        self.process.stdin = Mock(write=sent.append)
        self.host.Shutdown()
        self.assertLoggedEqual('shutdown command', [{'type': 'shutdown'}], [json.loads(line) for line in sent])
