import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from PySubtrans.Helpers.TestCases import LoggedTestCase
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
            found = Discovery.FindExistingTorch()

        self.assertLoggedEqual('default location returned', os.path.join('app', Discovery.DEFAULT_TORCH_DIR_NAME), found)

    def test_find_existing_torch_returns_none_when_absent(self) -> None:
        """No default install and no importable Torch yields None."""
        with patch.object(Discovery, 'GetAppDir', return_value='app'), \
                patch.object(Discovery, 'HasTorchPackage', return_value=False), \
                patch.object(Discovery.importlib.util, 'find_spec', return_value=None):
            found = Discovery.FindExistingTorch()

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
