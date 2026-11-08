import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Helpers.Tests import skip_if_debugger_attached
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.Transcription.Torch import Discovery


class TestTorchDiscovery(LoggedTestCase):
    """Verify interpreter and existing-installation discovery without Qt."""

    def test_python_meets_minimum_accepts_current_interpreter(self) -> None:
        """The running interpreter (>=3.10, per project requirements) passes the floor check."""
        self.assertLoggedTrue('current interpreter satisfies torch minimum', Discovery.PythonMeetsMinimum(sys.executable))

    def test_python_meets_minimum_rejects_old_version(self) -> None:
        """An interpreter reporting a version below 3.10 is rejected."""
        fake_result = subprocess.CompletedProcess(args=[], returncode=0, stdout='3.9\n')
        with patch.object(Discovery.subprocess, 'run', return_value=fake_result):
            self.assertLoggedFalse('Python 3.9 does not satisfy the torch minimum', Discovery.PythonMeetsMinimum('fake-python'))

    def test_python_meets_minimum_rejects_missing_interpreter(self) -> None:
        """A candidate that cannot be executed is rejected rather than raising."""
        with patch.object(Discovery.subprocess, 'run', side_effect=OSError('not found')):
            self.assertLoggedFalse('missing interpreter is rejected', Discovery.PythonMeetsMinimum('does-not-exist'))

    def test_find_existing_torch_prefers_default_location(self) -> None:
        """The install location beside the application is checked first."""
        with patch.object(Discovery, 'GetAppDir', return_value='app'), \
                patch.object(Discovery, 'HasTorchPackage', return_value=True):
            found = Discovery.FindExistingTorch('envqwen')

        self.assertLoggedEqual('default location returned', os.path.join('app', 'envqwen'), found)

    def test_find_existing_torch_returns_none_when_absent(self) -> None:
        """No default install and no importable Torch yields None."""
        with patch.object(Discovery, 'GetAppDir', return_value='app'), \
                patch.object(Discovery, 'HasTorchPackage', return_value=False), \
                patch.object(Discovery.importlib.util, 'find_spec', return_value=None):
            found = Discovery.FindExistingTorch('envqwen')

        self.assertLoggedIsNone('no installation found', found)

    def test_find_compatible_python_prefers_abi_match_over_newer_interpreter(self) -> None:
        """A matching interpreter is selected ahead of a newer mismatched one."""
        frozen = {
            'python_implementation': 'cpython', 'python_abi': 'cpython-312',
            'python_version': '3.12', 'os': 'Windows', 'architecture': 'AMD64', 'pointer_bits': 64,
        }
        mismatched = dict(frozen)
        mismatched['python_abi'] = 'cpython-313'
        mismatched['python_version'] = '3.13'
        matching = dict(frozen)

        with patch.object(sys, 'frozen', True, create=True), \
                patch.object(Discovery, 'CandidatePythons', return_value=['/newer/python3.13', '/matching/python3.12']), \
                patch.object(Discovery, 'ExpectedCompatibility', return_value=frozen), \
                patch.object(Discovery, 'ProbeVenvCompatibility', side_effect=[mismatched, matching]):
            chosen = Discovery.FindCompatiblePython()

        self.assertLoggedEqual('matching interpreter selected', '/matching/python3.12', chosen)

    def test_find_compatible_python_falls_back_when_no_match(self) -> None:
        """Without an ABI match the newest usable interpreter is still returned."""
        frozen = {'python_abi': 'cpython-312', 'python_version': '3.12'}

        with patch.object(sys, 'frozen', True, create=True), \
                patch.object(Discovery, 'CandidatePythons', return_value=['/newer/python3.13']), \
                patch.object(Discovery, 'ExpectedCompatibility', return_value=frozen), \
                patch.object(Discovery, 'ProbeVenvCompatibility', return_value={'python_abi': 'cpython-313'}), \
                patch.object(Discovery, 'PythonMeetsMinimum', return_value=True):
            chosen = Discovery.FindCompatiblePython()

        self.assertLoggedEqual('fallback interpreter selected', '/newer/python3.13', chosen)

    def test_py_launcher_interpreters_handles_path_with_space(self) -> None:
        """A launcher entry whose install path contains a space is still recognised."""
        with tempfile.TemporaryDirectory() as directory:
            program_files = Path(directory) / 'Program Files' / 'Python312'
            program_files.mkdir(parents=True)
            python_exe = program_files / 'python.exe'
            python_exe.write_text('')

            fake_result = subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout=f' -V:3.12 *        {python_exe}\n',
            )
            with patch.object(Discovery.subprocess, 'run', return_value=fake_result):
                interpreters = Discovery._PyLauncherInterpreters('py')

        self.assertLoggedEqual('full path with space recovered', [str(python_exe)], interpreters)

    def test_expected_compatibility_uses_running_interpreter_when_not_frozen(self) -> None:
        """A source run checks selected environments against its own interpreter."""
        with patch.object(Discovery, 'FindCompatibilityMetadata', return_value=None), \
                patch.object(Discovery, 'BuildCurrentCompatibility', return_value={'python_abi': 'cpython-313'}) as build:
            compatibility = Discovery.ExpectedCompatibility()

        self.assertLoggedEqual('running interpreter is the reference', {'python_abi': 'cpython-313'}, compatibility)
        self.assertLoggedEqual('running interpreter queried once', 1, build.call_count)


class TestEnvironmentInterpreter(LoggedTestCase):
    """Resolve virtual environments with mocked filesystem predicates."""

    def test_venv_and_site_packages(self) -> None:
        """Windows and POSIX layouts resolve regardless of the app's Python version."""
        for root, sites, relative in (('venv', 'venv/Lib/site-packages', 'Scripts/python.exe'),
                                      ('venv', 'venv/lib/python3.11/site-packages', 'bin/python')):
            expected = Path(root).absolute() / relative
            with patch.object(Path, 'is_file', lambda path: path == expected):
                self.assertLoggedEqual('root interpreter', str(expected), Discovery.ResolveEnvironmentPython(root))
                self.assertLoggedEqual('site-packages interpreter', str(expected), Discovery.ResolveEnvironmentPython(sites))

    def test_source_fallback(self) -> None:
        """An older source install can still use Qwen in the app's interpreter."""
        with patch.object(Discovery.sys, 'frozen', False, create=True), \
                patch.object(Discovery, 'GetAppDir', return_value='app'), \
                patch.object(Path, 'is_file', return_value=False):
            self.assertLoggedEqual('source Python', Discovery.sys.executable, Discovery.ResolveEnvironmentPython(None, 'envqwen'))

    def test_source_prefers_runtime_default(self) -> None:
        """The runtime-specific environment beside the application takes precedence."""
        root = Path('app').absolute()
        for relative in ('Scripts/python.exe', 'bin/python'):
            expected = root / 'envqwen' / relative
            with patch.object(Discovery.sys, 'frozen', False, create=True), \
                    patch.object(Discovery, 'GetAppDir', return_value=str(root)), \
                    patch.object(Path, 'is_file', lambda path: path == expected):
                self.assertLoggedEqual('default runtime Python', str(expected), Discovery.ResolveEnvironmentPython(None, 'envqwen'))

    def test_explicit_environment_overrides_default(self) -> None:
        """An explicit setting is authoritative even when a default environment exists."""
        expected = Path('custom').absolute() / 'Scripts/python.exe'
        with patch.object(Path, 'is_file', lambda path: path == expected), \
                patch.object(Discovery, 'GetAppDir') as app_dir:
            actual = Discovery.ResolveEnvironmentPython('custom', 'envqwen')

        self.assertLoggedEqual('configured Python', str(expected), actual)
        self.assertLoggedEqual('default directory not consulted', 0, app_dir.call_count)

    @skip_if_debugger_attached
    def test_missing_interpreter(self) -> None:
        """Invalid environments and unconfigured frozen builds fail explicitly."""
        with patch.object(Path, 'is_file', return_value=False):
            with self.assertRaises(SubtitleError):
                Discovery.ResolveEnvironmentPython('missing')
        with patch.object(Discovery.sys, 'frozen', True, create=True), \
                patch.object(Path, 'is_file', return_value=True) as exists:
            with self.assertRaises(SubtitleError):
                Discovery.ResolveEnvironmentPython(None, 'envqwen')

        self.assertLoggedEqual('frozen build does not try a source default', 0, exists.call_count)
