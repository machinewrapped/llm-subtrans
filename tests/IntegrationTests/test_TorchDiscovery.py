import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Helpers.Tests import skip_if_debugger_attached
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.Transcription.Torch import Discovery, Validation


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
        with patch.object(Discovery, 'ApplicationRoot', return_value=Path('app')), \
                patch.object(Discovery, 'HasTorchPackage', return_value=True):
            found = Discovery.FindExistingTorch('envqwen', lambda _root: False)

        self.assertLoggedEqual('default location returned', os.path.join('app', 'envqwen'), found)

    def test_find_existing_torch_returns_none_when_absent(self) -> None:
        """No default install and no importable Torch yields None."""
        with patch.object(Discovery, 'ApplicationRoot', return_value=Path('app')), \
                patch.object(Discovery, 'HasTorchPackage', return_value=False), \
                patch.object(Discovery.importlib.util, 'find_spec', return_value=None):
            found = Discovery.FindExistingTorch('envqwen', lambda _root: True)

        self.assertLoggedIsNone('no installation found', found)

    def test_find_existing_torch_on_path_needs_runtime(self) -> None:
        """The Torch environment on the path is offered only if it has the runtime, since it may belong to another one."""
        with patch.object(Discovery, 'FindDefaultEnvironment', return_value=None), \
                patch.object(Discovery, 'FindTorchOnPath', return_value='other_env'):
            with_runtime = Discovery.FindExistingTorch('envqwen', lambda _root: True)
            without_runtime = Discovery.FindExistingTorch('envqwen', lambda _root: False)

        self.assertLoggedEqual('environment with the runtime offered', 'other_env', with_runtime)
        self.assertLoggedIsNone('environment without the runtime not offered', without_runtime)

    def test_find_torch_site_packages_recognises_other_python_version(self) -> None:
        """A venv from another Python minor version is still detected."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site_packages = root / 'lib' / 'python3.9' / 'site-packages'
            (site_packages / 'torch').mkdir(parents=True)

            found = Validation.FindTorchSitePackages(root)

        self.assertLoggedEqual('versioned POSIX layout detected', site_packages.resolve(), found)

    def test_find_compatible_python_uses_first_frozen_candidate_meeting_minimum(self) -> None:
        """A frozen build selects the first candidate that meets the Python floor."""
        with patch.object(sys, 'frozen', True, create=True), \
                patch.object(Discovery, 'CandidatePythons', return_value=['/old/python3.9', '/first/python3.10', '/later/python3.13']), \
                patch.object(Discovery, 'PythonMeetsMinimum', side_effect=[False, True]) as meets_minimum:
            chosen = Discovery.FindCompatiblePython()

        self.assertLoggedEqual('first usable interpreter selected', '/first/python3.10', chosen)
        self.assertLoggedEqual('candidates checked in order', ['/old/python3.9', '/first/python3.10'],
                               [call.args[0] for call in meets_minimum.call_args_list])

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
                patch.object(Discovery, 'ApplicationRoot', return_value=Path('app')), \
                patch.object(Path, 'is_file', return_value=False):
            self.assertLoggedEqual('source Python', Discovery.sys.executable, Discovery.ResolveEnvironmentPython(None, 'envqwen'))

    def test_source_prefers_runtime_default(self) -> None:
        """The runtime-specific environment beside the application takes precedence."""
        root = Path('app').absolute()
        for relative in ('Scripts/python.exe', 'bin/python'):
            expected = root / 'envqwen' / relative
            with patch.object(Discovery.sys, 'frozen', False, create=True), \
                    patch.object(Discovery, 'ApplicationRoot', return_value=root), \
                    patch.object(Path, 'is_file', lambda path: path == expected):
                self.assertLoggedEqual('default runtime Python', str(expected), Discovery.ResolveEnvironmentPython(None, 'envqwen'))

    def test_explicit_environment_overrides_default(self) -> None:
        """An explicit setting is authoritative even when a default environment exists."""
        expected = Path('custom').absolute() / 'Scripts/python.exe'
        with patch.object(Path, 'is_file', lambda path: path == expected), \
                patch.object(Discovery, 'ApplicationRoot') as app_dir:
            actual = Discovery.ResolveEnvironmentPython('custom', 'envqwen')

        self.assertLoggedEqual('configured Python', str(expected), actual)
        self.assertLoggedEqual('default directory not consulted', 0, app_dir.call_count)

    def test_source_root_ignores_working_directory(self) -> None:
        """A source install finds its default environments in the project root, not the working directory."""
        project_root = Path(__file__).resolve().parents[2]
        with patch.object(Discovery.sys, 'frozen', False, create=True), \
                patch.object(Discovery, 'GetAppDir', return_value='elsewhere'):
            self.assertLoggedEqual('project root', project_root, Discovery.ApplicationRoot())

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
