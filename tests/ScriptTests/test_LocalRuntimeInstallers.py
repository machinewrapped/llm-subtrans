"""Source runtime installers exercised without creating venvs or running pip."""

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Helpers.Tests import skip_if_debugger_attached
from PySubtrans.Transcription.Torch.Hardware import HardwareDetection
from PySubtrans.Transcription.Torch.QwenRuntime import QwenAsrPipArguments
from scripts import install_qwen_runtime, install_torch


class TestPrepareRuntimeEnvironment(LoggedTestCase):
    """Venv creation and interpreter validation use mocked subprocesses."""

    def test_creates_missing_environment(self) -> None:
        """The app interpreter creates the venv and validates its resulting Python."""
        root = Path('runtime')
        with patch.object(install_torch, 'FindEnvironmentPython', side_effect=[None, 'runtime-python']), \
                patch.object(install_torch, 'PythonMeetsMinimum', return_value=True) as minimum, \
                patch.object(install_torch.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run:
            python = install_torch.PrepareEnvironment(root)

        self.assertLoggedEqual('target Python', 'runtime-python', python)
        self.assertLoggedEqual('venv creation', [sys.executable, '-m', 'venv', str(root)], run.call_args.args[0])
        self.assertLoggedEqual('creator and target validated', [sys.executable, 'runtime-python'],
                               [call.args[0] for call in minimum.call_args_list])

    def test_reuses_existing_environment(self) -> None:
        """A valid existing environment is not recreated or checked for an ABI match."""
        with patch.object(install_torch, 'FindEnvironmentPython', return_value='existing-python'), \
                patch.object(install_torch, 'PythonMeetsMinimum', return_value=True) as minimum, \
                patch.object(install_torch.subprocess, 'run') as run:
            python = install_torch.PrepareEnvironment(Path('existing'))

        self.assertLoggedEqual('existing interpreter', 'existing-python', python)
        self.assertLoggedEqual('only target version checked', ['existing-python'], [call.args[0] for call in minimum.call_args_list])
        self.assertLoggedEqual('no environment creation', 0, run.call_count)

    def test_rejects_old_creator(self) -> None:
        """An unsupported creator cannot start venv creation."""
        with patch.object(install_torch, 'FindEnvironmentPython', return_value=None), \
                patch.object(install_torch, 'PythonMeetsMinimum', return_value=False), \
                patch.object(install_torch.subprocess, 'run') as run, self.assertLogs(level='ERROR'):
            python = install_torch.PrepareEnvironment(Path('runtime'))

        self.assertLoggedIsNone('no usable runtime', python)
        self.assertLoggedEqual('no creation attempted', 0, run.call_count)

    def test_creation_failure(self) -> None:
        """A failed venv subprocess cannot supply an interpreter to pip."""
        with patch.object(install_torch, 'FindEnvironmentPython', return_value=None), \
                patch.object(install_torch, 'PythonMeetsMinimum', return_value=True), \
                patch.object(install_torch.subprocess, 'run', return_value=SimpleNamespace(returncode=7)), self.assertLogs(level='ERROR'):
            python = install_torch.PrepareEnvironment(Path('runtime'))

        self.assertLoggedIsNone('failed creation', python)

    def test_rejects_old_target(self) -> None:
        """An existing interpreter below Python 3.10 is not reused."""
        with patch.object(install_torch, 'FindEnvironmentPython', return_value='old-python'), \
                patch.object(install_torch, 'PythonMeetsMinimum', return_value=False), self.assertLogs(level='ERROR'):
            python = install_torch.PrepareEnvironment(Path('runtime'))

        self.assertLoggedIsNone('old runtime rejected', python)

    def test_creation_without_interpreter(self) -> None:
        """A nominally successful venv command must still leave a discoverable interpreter."""
        with patch.object(install_torch, 'FindEnvironmentPython', return_value=None), \
                patch.object(install_torch, 'PythonMeetsMinimum', return_value=True), \
                patch.object(install_torch.subprocess, 'run', return_value=SimpleNamespace(returncode=0)), self.assertLogs(level='ERROR'):
            python = install_torch.PrepareEnvironment(Path('runtime'))

        self.assertLoggedIsNone('incomplete environment rejected', python)


class TestTargetTorchInstaller(LoggedTestCase):
    """Torch probes and installations target the runtime rather than envsubtrans."""

    @skip_if_debugger_attached
    def test_gpu_probe_backends(self) -> None:
        """The standalone probe recognizes CUDA, MPS and XPU without loading real Torch."""
        for selected in ('cuda', 'mps', 'xpu', 'cpu'):
            torch = SimpleNamespace(
                cuda=SimpleNamespace(is_available=lambda: selected == 'cuda'),
                backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: selected == 'mps')),
                xpu=SimpleNamespace(is_available=lambda: selected == 'xpu'))
            with patch.object(importlib, 'import_module', return_value=torch), self.assertRaises(SystemExit) as raised:
                exec(install_torch._GPU_PROBE, {})

            self.assertLoggedEqual('accelerator availability', 2 if selected == 'cpu' else 0, raised.exception.code)

    def test_existing_gpu_skips_install(self) -> None:
        """Only the target's GPU probe can bypass hardware detection and pip."""
        with patch.object(install_torch.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run, \
                patch.object(install_torch, 'DetectHardware') as detect:
            code = install_torch.InstallTorch('target-python')

        self.assertLoggedEqual('GPU success', 0, code)
        self.assertLoggedEqual('target probed', ['target-python', '-I', '-c'], run.call_args.args[0][:3])
        self.assertLoggedEqual('no pip call', 1, run.call_count)
        self.assertLoggedEqual('no hardware detection', 0, detect.call_count)

    def test_hardware_builds(self) -> None:
        """CUDA installs from its own index only and Apple MPS uses the default wheel."""
        for index_url in ('https://example.invalid/cuda', ''):
            detection = HardwareDetection('GPU', index_url, True)
            with patch.object(install_torch, 'DetectHardware', return_value=detection), \
                    patch.object(install_torch.subprocess, 'run', side_effect=[SimpleNamespace(returncode=1), SimpleNamespace(returncode=0)]) as run:
                code = install_torch.InstallTorch('target-python')

            expected = ['target-python', '-m', 'pip', 'install', 'torch']
            if index_url:
                expected.extend(['--index-url', index_url])

            self.assertLoggedEqual('GPU installation exit', 0, code)
            self.assertLoggedEqual('hardware-specific pip invocation', expected, run.call_args.args[0])

    def test_cpu_build_replaced_on_gpu_hardware(self) -> None:
        """An installed CPU-only build is removed before the GPU build, since pip would keep it."""
        detection = HardwareDetection('GPU', 'https://example.invalid/cuda', True)
        responses = [SimpleNamespace(returncode=2), SimpleNamespace(returncode=0), SimpleNamespace(returncode=0)]
        with patch.object(install_torch, 'DetectHardware', return_value=detection), \
                patch.object(install_torch.subprocess, 'run', side_effect=responses) as run:
            code = install_torch.InstallTorch('target-python')

        commands = [call.args[0] for call in run.call_args_list]
        self.assertLoggedEqual('GPU installation exit', 0, code)
        self.assertLoggedEqual('CPU build removed', ['target-python', '-m', 'pip', 'uninstall', '-y', 'torch'], commands[1])
        self.assertLoggedEqual('GPU build installed', ['target-python', '-m', 'pip', 'install', 'torch', '--index-url', detection.index_url], commands[2])

    def test_cpu_install_and_failure_codes(self) -> None:
        """CPU-only success is distinct from a failed pip operation."""
        for pip_code, expected in ((0, 1), (9, 2)):
            with patch.object(install_torch, 'DetectHardware', return_value=None), \
                    patch.object(install_torch.subprocess, 'run', side_effect=[SimpleNamespace(returncode=1), SimpleNamespace(returncode=pip_code)]) as run:
                if pip_code:
                    with self.assertLogs(level='ERROR'):
                        code = install_torch.InstallTorch('target-python')
                else:
                    code = install_torch.InstallTorch('target-python')

            self.assertLoggedEqual('CPU status', expected, code)
            self.assertLoggedEqual('CPU pip target', ['target-python', '-m', 'pip', 'install', 'torch'], run.call_args.args[0])

    @skip_if_debugger_attached
    def test_missing_interpreter(self) -> None:
        """Subprocess failures return the installer failure code."""
        with patch.object(install_torch.subprocess, 'run', side_effect=OSError('missing')), self.assertLogs(level='ERROR'):
            code = install_torch.InstallTorch('missing-python')

        self.assertLoggedEqual('failure status', 2, code)


class TestQwenRuntimeInstaller(LoggedTestCase):
    """Qwen follows environment creation and Torch with its own target pip steps."""

    def setUp(self) -> None:
        super().setUp()
        self.root = Path('envqwen')
        self.site_packages = self.root / 'Lib/site-packages'
        self.dependencies = ['install', '--no-warn-conflicts', 'transformers==4.57.6']

    def test_full_installation_order_and_target_metadata(self) -> None:
        """Both GPU and CPU installs create a venv and use only its pip and metadata."""
        for is_gpu, expected in ((True, 0), (False, 1)):
            detection = HardwareDetection('hardware', 'https://example.invalid/cuda', True) if is_gpu else None
            with patch.object(install_torch, 'FindEnvironmentPython', side_effect=[None, 'target-python']), \
                    patch.object(install_torch, 'PythonMeetsMinimum', return_value=True), \
                    patch.object(install_torch, 'DetectHardware', return_value=detection), \
                    patch.object(install_qwen_runtime, 'FindTorchSitePackages', return_value=self.site_packages), \
                    patch.object(install_qwen_runtime, 'QwenDependencyPipArguments', return_value=self.dependencies) as dependencies, \
                    patch.object(install_qwen_runtime.subprocess, 'run', side_effect=[SimpleNamespace(returncode=0), SimpleNamespace(returncode=1),
                                                                                 SimpleNamespace(returncode=0), SimpleNamespace(returncode=0), SimpleNamespace(returncode=0)]) as run:
                code = install_qwen_runtime.InstallQwenRuntime(self.root)

            commands = [call.args[0] for call in run.call_args_list]
            self.assertLoggedEqual('final accelerator status', expected, code)
            self.assertLoggedEqual('venv created first', [sys.executable, '-m', 'venv', str(self.root)], commands[0])
            self.assertLoggedEqual('Torch pip before Qwen', ['target-python', '-m', 'pip', 'install', 'torch'], commands[2][:5])
            self.assertLoggedEqual('Qwen package pip', ['target-python', '-m', 'pip', *QwenAsrPipArguments()], commands[3])
            self.assertLoggedEqual('Qwen dependency pip', ['target-python', '-m', 'pip', *self.dependencies], commands[4])
            self.assertLoggedEqual('metadata read only from target', [str(self.site_packages)], dependencies.call_args.args[0])

    def test_failed_preparation_stops_install(self) -> None:
        """An invalid environment cannot trigger Torch or Qwen installations."""
        with patch.object(install_qwen_runtime, 'PrepareEnvironment', return_value=None), \
                patch.object(install_qwen_runtime, 'InstallTorch') as torch, \
                patch.object(install_qwen_runtime.subprocess, 'run') as run:
            code = install_qwen_runtime.InstallQwenRuntime(self.root)

        self.assertLoggedEqual('failure status', 2, code)
        self.assertLoggedEqual('no Torch installation', 0, torch.call_count)
        self.assertLoggedEqual('no Qwen installation', 0, run.call_count)

    def test_cli_directory_and_cpu_status(self) -> None:
        """The CLI resolves its target directory and preserves CPU-only success."""
        with patch.object(install_qwen_runtime.sys, 'argv', ['install_qwen_runtime.py', 'runtime folder']), \
                patch.object(install_qwen_runtime, 'InstallQwenRuntime', return_value=1) as install:
            code = install_qwen_runtime.main()

        self.assertLoggedEqual('CPU-only CLI status', 1, code)
        self.assertLoggedEqual('absolute runtime target', Path('runtime folder').absolute(), install.call_args.args[0])

    def test_failed_torch_stops_qwen_install(self) -> None:
        """Torch failure does not start Qwen's dependency resolution."""
        with patch.object(install_qwen_runtime, 'PrepareEnvironment', return_value='target-python'), \
                patch.object(install_qwen_runtime, 'InstallTorch', return_value=2), \
                patch.object(install_qwen_runtime.subprocess, 'run') as run, self.assertLogs(level='WARNING'):
            code = install_qwen_runtime.InstallQwenRuntime(self.root)

        self.assertLoggedEqual('failure status', 2, code)
        self.assertLoggedEqual('no Qwen pip invocation', 0, run.call_count)

    def test_runtime_pip_failures(self) -> None:
        """Neither package nor dependency failures can be mistaken for CPU success."""
        for pip_codes in ([7], [0, 1]):
            with patch.object(install_qwen_runtime, 'PrepareEnvironment', return_value='target-python'), \
                    patch.object(install_qwen_runtime, 'InstallTorch', return_value=0), \
                    patch.object(install_qwen_runtime, 'FindTorchSitePackages', return_value=self.site_packages), \
                    patch.object(install_qwen_runtime, 'QwenDependencyPipArguments', return_value=self.dependencies), \
                    patch.object(install_qwen_runtime.subprocess, 'run', side_effect=[SimpleNamespace(returncode=code) for code in pip_codes]) as run, \
                    self.assertLogs(level='ERROR'):
                code = install_qwen_runtime.InstallQwenRuntime(self.root)

            self.assertLoggedEqual('failure status', 2, code)
            self.assertLoggedEqual('stopped at first failed pip step', len(pip_codes), run.call_count)

    def test_missing_target_metadata(self) -> None:
        """Do not fall back to dependencies from the app's environment."""
        for site_packages in (None, self.site_packages):
            with patch.object(install_qwen_runtime, 'PrepareEnvironment', return_value='target-python'), \
                    patch.object(install_qwen_runtime, 'InstallTorch', return_value=0), \
                    patch.object(install_qwen_runtime, 'FindTorchSitePackages', return_value=site_packages), \
                    patch.object(install_qwen_runtime, 'QwenDependencyPipArguments', return_value=None), \
                    patch.object(install_qwen_runtime.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run, self.assertLogs(level='ERROR'):
                code = install_qwen_runtime.InstallQwenRuntime(self.root)

            self.assertLoggedEqual('failure status', 2, code)
            self.assertLoggedEqual('dependency pip not run', 1, run.call_count)

    @skip_if_debugger_attached
    def test_subprocess_failure(self) -> None:
        """OS failures use the same failure code as pip failures."""
        with patch.object(install_qwen_runtime, 'PrepareEnvironment', side_effect=OSError('cannot create')), self.assertLogs(level='ERROR'):
            code = install_qwen_runtime.InstallQwenRuntime(self.root)

        self.assertLoggedEqual('failure status', 2, code)
