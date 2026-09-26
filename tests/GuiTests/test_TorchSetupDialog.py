import tempfile
from pathlib import Path
from unittest.mock import patch

from tests.GuiTestSupport import ConfigureOffscreenPlatform

ConfigureOffscreenPlatform()

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication, QMessageBox

from GuiSubtrans.Widgets.TorchSetupDialog import TorchSetupDialog
from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Transcription.Torch.QwenRuntime import QwenAsrPipArguments
from PySubtrans.Transcription.Torch.Hardware import (
    DetectHardware,
    HardwareDetection,
    SelectCudaBuild,
)


class TestTorchSetupSelection(LoggedTestCase):
    """Verify Torch selection follows the driver's reported CUDA capability."""

    application : QApplication

    _CUDA_BUILDS : list[tuple[str, str, str]] = [
        ('13.0', '580.65', 'https://download.pytorch.org/whl/cu130'),
        ('12.6', '560.70', 'https://download.pytorch.org/whl/cu126'),
    ]

    def test_reported_cuda_capability_selects_available_build(self) -> None:
        """A newer driver report selects the newest available PyTorch build."""
        selected = SelectCudaBuild('616.56', '13.4', self._CUDA_BUILDS)

        self.assertLoggedEqual(
            'cu130 selected for CUDA 13.4 driver capability',
            ('13.0', 'https://download.pytorch.org/whl/cu130'),
            selected,
        )

    def test_reported_cuda_capability_limits_build_selection(self) -> None:
        """A driver capable of only CUDA 12.6 does not select a newer wheel."""
        selected = SelectCudaBuild('616.56', '12.6', self._CUDA_BUILDS)

        self.assertLoggedEqual(
            'cu126 selected for CUDA 12.6 driver capability',
            ('12.6', 'https://download.pytorch.org/whl/cu126'),
            selected,
        )

    def test_hardware_detection_reports_driver_cuda_capability(self) -> None:
        """The hardware description tells the user what the driver reported."""
        with patch('PySubtrans.Transcription.Torch.Hardware.sys.platform', 'linux'), \
                patch('PySubtrans.Transcription.Torch.Hardware.DetectNvidiaDriver', return_value='616.56'), \
                patch('PySubtrans.Transcription.Torch.Hardware.DetectNvidiaCudaVersion', return_value='13.4'):
            hardware = DetectHardware()

        self.assertLoggedIsNotNone('hardware detection result', hardware)
        if hardware is not None:
            self.assertLoggedEqual('cu130 wheel index', 'https://download.pytorch.org/whl/cu130', hardware.index_url)
            self.assertLoggedIn('reported CUDA version', 'CUDA 13.4', hardware.description)

    @classmethod
    def setUpClass(cls) -> None:
        """Create the shared Qt application for dialog interaction tests."""
        super().setUpClass()
        existing = QApplication.instance()
        cls.application = existing if isinstance(existing, QApplication) else QApplication([])

    def setUp(self) -> None:
        """Treat environments as having the Qwen runtime unless a test says otherwise."""
        super().setUp()
        needs_runtime = patch('GuiSubtrans.Widgets.TorchSetupDialog.NeedsQwenRuntime', return_value=False)
        self.needs_qwen_runtime = needs_runtime.start()
        self.addCleanup(needs_runtime.stop)

    def _new_dialog(self) -> TorchSetupDialog:
        """Create a dialog with existing-installation detection disabled."""
        with patch('GuiSubtrans.Widgets.TorchSetupDialog.FindExistingTorch', return_value=None):
            return TorchSetupDialog()

    def _dispose(self, dialog : TorchSetupDialog) -> None:
        """Release a dialog after a test."""
        dialog.deleteLater()
        self.application.processEvents()

    def test_cpu_fallback_requires_explicit_confirmation(self) -> None:
        """A detected GPU without a driver cannot silently install CPU Torch."""
        hardware = HardwareDetection(
            'NVIDIA GPU detected, but its driver is unavailable',
            'https://download.pytorch.org/whl/cpu',
            False,
            'Install the latest NVIDIA driver, restart, and try again.',
            hardware_detected=True,
        )
        with patch('GuiSubtrans.Widgets.TorchSetupDialog.DetectHardware', return_value=hardware):
            dialog = self._new_dialog()

        try:
            dialog._show_page(1)
            self.assertLoggedFalse('CPU install requires confirmation', dialog._next_button.isEnabled())
            if dialog._cpu_fallback_checkbox is not None:
                self.assertLoggedFalse('CPU fallback is initially unchecked', dialog._cpu_fallback_checkbox.isChecked())
                dialog._cpu_fallback_checkbox.setChecked(True)
                self.assertLoggedTrue('CPU install enabled after confirmation', dialog._next_button.isEnabled())
        finally:
            self._dispose(dialog)

    def test_manual_path_enables_continue_and_is_used_directly(self) -> None:
        """Selecting the manual-locate option validates the typed path without an install step."""
        dialog = self._new_dialog()

        try:
            dialog._manual_radio.setChecked(True)
            self.assertLoggedFalse('continue disabled with empty manual path', dialog._next_button.isEnabled())

            dialog._manual_path_field.setText('/some/torch/env')
            self.assertLoggedTrue('continue enabled once a manual path is entered', dialog._next_button.isEnabled())

            with patch.object(dialog, '_validate_and_accept') as mock_validate:
                dialog._on_next()

            mock_validate.assert_called_once_with('/some/torch/env')
        finally:
            self._dispose(dialog)

    def test_validate_rejects_environment_without_torch(self) -> None:
        """A selected path with no discoverable Torch package is not accepted."""
        dialog = self._new_dialog()

        try:
            with tempfile.TemporaryDirectory() as directory, \
                    patch('GuiSubtrans.Widgets.TorchSetupDialog.QMessageBox.warning') as warning, \
                    patch('GuiSubtrans.Widgets.TorchSetupDialog.QMessageBox.information') as information:
                accepted = dialog._validate_and_accept(directory)

            self.assertLoggedFalse('environment without Torch is rejected', accepted)
            self.assertLoggedEqual('user is warned', 1, warning.call_count)
            self.assertLoggedEqual('dialog is not accepted', 0, information.call_count)
        finally:
            self._dispose(dialog)

    def test_validate_warns_but_accepts_on_abi_mismatch(self) -> None:
        """A mismatched interpreter produces a strong warning, not a blocker."""
        dialog = self._new_dialog()

        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / 'torch').mkdir()
                frozen = {
                    'python_implementation': 'cpython', 'python_abi': 'cpython-312',
                    'python_version': '3.12', 'os': 'Windows', 'architecture': 'AMD64', 'pointer_bits': 64,
                }
                actual = dict(frozen)
                actual['python_abi'] = 'cpython-313'
                actual['python_version'] = '3.13'

                with patch('GuiSubtrans.Widgets.TorchSetupDialog.ExpectedCompatibility', return_value=frozen), \
                        patch('GuiSubtrans.Widgets.TorchSetupDialog.FindVenvPython', return_value=root / 'python.exe'), \
                        patch('GuiSubtrans.Widgets.TorchSetupDialog.ProbeVenvCompatibility', return_value=actual), \
                        patch('GuiSubtrans.Widgets.TorchSetupDialog.QMessageBox.warning') as warning, \
                        patch('GuiSubtrans.Widgets.TorchSetupDialog.QMessageBox.information') as information:
                    accepted = dialog._validate_and_accept(directory)

            self.assertLoggedTrue('mismatched environment is still accepted', accepted)
            self.assertLoggedEqual('user is warned about compatibility', 1, warning.call_count)
            self.assertLoggedEqual('restart prompt shown', 1, information.call_count)
        finally:
            self._dispose(dialog)

    def test_validate_warns_on_mismatch_in_source_run(self) -> None:
        """A source run warns about a mismatched manually selected environment."""
        dialog = self._new_dialog()

        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / 'torch').mkdir()

                with patch('GuiSubtrans.Widgets.TorchSetupDialog.ExpectedCompatibility', return_value={'python_abi': 'cpython-312', 'python_version': '3.12'}), \
                        patch('GuiSubtrans.Widgets.TorchSetupDialog.FindVenvPython', return_value=root / 'python.exe'), \
                        patch('GuiSubtrans.Widgets.TorchSetupDialog.ProbeVenvCompatibility', return_value={'python_abi': 'cpython-313', 'python_version': '3.13'}), \
                        patch('GuiSubtrans.Widgets.TorchSetupDialog.QMessageBox.warning') as warning, \
                        patch('GuiSubtrans.Widgets.TorchSetupDialog.QMessageBox.information'):
                    accepted = dialog._validate_and_accept(directory)

            self.assertLoggedTrue('mismatched source environment is still accepted', accepted)
            self.assertLoggedEqual('user is warned', 1, warning.call_count)
        finally:
            self._dispose(dialog)

    def test_validate_skips_probe_when_source_path_has_no_interpreter(self) -> None:
        """A source path without a discoverable interpreter does not warn spuriously."""
        dialog = self._new_dialog()

        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / 'torch').mkdir()

                with patch('GuiSubtrans.Widgets.TorchSetupDialog.ExpectedCompatibility', return_value={'python_abi': 'cpython-313'}), \
                        patch('GuiSubtrans.Widgets.TorchSetupDialog.FindVenvPython', return_value=None), \
                        patch('GuiSubtrans.Widgets.TorchSetupDialog.QMessageBox.warning') as warning, \
                        patch('GuiSubtrans.Widgets.TorchSetupDialog.QMessageBox.information'):
                    accepted = dialog._validate_and_accept(directory)

            self.assertLoggedTrue('environment without interpreter is accepted in source mode', accepted)
            self.assertLoggedEqual('no spurious warning', 0, warning.call_count)
        finally:
            self._dispose(dialog)

    def test_automatic_install_adds_qwen_runtime_after_torch(self) -> None:
        """A new environment gets Torch, then qwen-asr without its dependencies, then the dependencies it declares."""
        dialog = self._new_dialog()

        try:
            with patch('GuiSubtrans.Widgets.TorchSetupDialog.FindCompatiblePython', return_value='python'), \
                    patch.object(dialog, '_run_steps') as run_steps:
                started = dialog._on_install()

            self.assertLoggedTrue('installation started', started)
            steps = run_steps.call_args.args[0]
            self.assertLoggedEqual('venv, Torch, qwen-asr and dependencies steps', 4, len(steps))

            venv_python = Path(dialog._target_dir) / 'Scripts' / 'python.exe'
            site_packages = Path(dialog._target_dir) / 'Lib' / 'site-packages'
            dependency_arguments = ['install', 'transformers==4.57.6']
            with patch('GuiSubtrans.Widgets.TorchSetupDialog.FindVenvPython', return_value=venv_python), \
                    patch('GuiSubtrans.Widgets.TorchSetupDialog.FindTorchSitePackages', return_value=site_packages), \
                    patch('GuiSubtrans.Widgets.TorchSetupDialog.QwenDependencyPipArguments', return_value=dependency_arguments) as dependency_pip_arguments:
                qwen_command = steps[2].command()
                dependencies_command = steps[3].command()

            self.assertLoggedEqual('qwen-asr installed with the venv pip', (str(venv_python), ['-m', 'pip', *QwenAsrPipArguments()]), qwen_command)
            self.assertLoggedEqual('dependencies read from the venv', [str(site_packages)], dependency_pip_arguments.call_args.args[0])
            self.assertLoggedEqual('dependencies installed with the venv pip', (str(venv_python), ['-m', 'pip', *dependency_arguments]), dependencies_command)
        finally:
            self._dispose(dialog)

    def test_missing_qwen_asr_metadata_fails_the_dependencies_step(self) -> None:
        """If qwen-asr's metadata cannot be read after installing it, the dependencies step fails rather than installing nothing."""
        dialog = self._new_dialog()

        try:
            dialog._target_dir = '/some/torch/env'
            steps = dialog._qwen_runtime_steps()

            with patch('GuiSubtrans.Widgets.TorchSetupDialog.FindTorchSitePackages', return_value=Path('/some/torch/env/Lib/site-packages')), \
                    patch('GuiSubtrans.Widgets.TorchSetupDialog.QwenDependencyPipArguments', return_value=None):
                command = steps[1].command()

            self.assertLoggedIsNone('no dependencies command', command)
        finally:
            self._dispose(dialog)

    def test_torch_only_environment_offers_qwen_runtime_install(self) -> None:
        """Selecting an environment set up for 1.7.0 installs the Qwen runtime into it before accepting it."""
        dialog = self._new_dialog()
        self.needs_qwen_runtime.return_value = True

        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / 'torch').mkdir()

                with patch('GuiSubtrans.Widgets.TorchSetupDialog.FindVenvPython', return_value=root / 'python.exe'), \
                        patch('GuiSubtrans.Widgets.TorchSetupDialog.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes), \
                        patch('GuiSubtrans.Widgets.TorchSetupDialog.QMessageBox.information') as information, \
                        patch.object(dialog, '_run_steps') as run_steps:
                    accepted = dialog._validate_and_accept(directory)

            self.assertLoggedFalse('environment not accepted until the runtime is installed', accepted)
            self.assertLoggedEqual('runtime steps started', 2, len(run_steps.call_args.args[0]))
            self.assertLoggedEqual('progress page shown', 2, dialog._current_page)
            self.assertLoggedEqual('failure returns to the first page', 0, dialog._retry_page)
            self.assertLoggedEqual('no restart prompt yet', 0, information.call_count)
        finally:
            self._dispose(dialog)

    def test_declining_qwen_runtime_install_leaves_environment_unselected(self) -> None:
        """The user can decline to install the Qwen runtime, and the environment is not selected."""
        dialog = self._new_dialog()
        self.needs_qwen_runtime.return_value = True

        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / 'torch').mkdir()

                with patch('GuiSubtrans.Widgets.TorchSetupDialog.FindVenvPython', return_value=root / 'python.exe'), \
                        patch('GuiSubtrans.Widgets.TorchSetupDialog.QMessageBox.question', return_value=QMessageBox.StandardButton.No), \
                        patch.object(dialog, '_run_steps') as run_steps:
                    accepted = dialog._validate_and_accept(directory)

            self.assertLoggedFalse('environment not accepted', accepted)
            self.assertLoggedEqual('nothing installed', 0, run_steps.call_count)
            self.assertLoggedEqual('no path chosen', '', dialog.chosen_path)
        finally:
            self._dispose(dialog)

    def test_environment_without_interpreter_cannot_get_qwen_runtime(self) -> None:
        """An environment with no interpreter to run pip is rejected rather than offered an install."""
        dialog = self._new_dialog()
        self.needs_qwen_runtime.return_value = True

        try:
            with tempfile.TemporaryDirectory() as directory:
                (Path(directory) / 'torch').mkdir()

                with patch('GuiSubtrans.Widgets.TorchSetupDialog.FindVenvPython', return_value=None), \
                        patch('GuiSubtrans.Widgets.TorchSetupDialog.QMessageBox.warning') as warning, \
                        patch('GuiSubtrans.Widgets.TorchSetupDialog.QMessageBox.question') as question:
                    accepted = dialog._validate_and_accept(directory)

            self.assertLoggedFalse('environment not accepted', accepted)
            self.assertLoggedEqual('user is warned', 1, warning.call_count)
            self.assertLoggedEqual('install not offered', 0, question.call_count)
        finally:
            self._dispose(dialog)

    def test_failed_step_stops_the_installation(self) -> None:
        """A failed installer step stops the sequence and lets the user go back."""
        dialog = self._new_dialog()

        try:
            dialog._target_dir = '/some/torch/env'
            steps = dialog._qwen_runtime_steps()

            with patch.object(dialog, '_start_process') as start_process, \
                    patch('GuiSubtrans.Widgets.TorchSetupDialog.FindVenvPython', return_value=Path('/some/torch/env/bin/python')):
                dialog._run_steps(steps)
                dialog._on_step_finished(1, QProcess.ExitStatus.NormalExit)

            self.assertLoggedEqual('only the first step started', 1, start_process.call_count)
            self.assertLoggedTrue('installation marked failed', dialog._installation_failed)
            self.assertLoggedTrue('back is available', dialog._back_button.isEnabled())
        finally:
            self._dispose(dialog)

    def test_successful_steps_run_in_sequence(self) -> None:
        """Each installer step starts only after the previous one succeeds."""
        dialog = self._new_dialog()

        try:
            dialog._target_dir = '/some/torch/env'
            steps = dialog._qwen_runtime_steps()

            with patch.object(dialog, '_start_process') as start_process, \
                    patch.object(dialog, '_on_steps_finished') as steps_finished, \
                    patch('GuiSubtrans.Widgets.TorchSetupDialog.FindVenvPython', return_value=Path('/some/torch/env/bin/python')), \
                    patch('GuiSubtrans.Widgets.TorchSetupDialog.FindTorchSitePackages', return_value=Path('/some/torch/env/Lib/site-packages')), \
                    patch('GuiSubtrans.Widgets.TorchSetupDialog.QwenDependencyPipArguments', return_value=['install', 'transformers==4.57.6']):
                dialog._run_steps(steps)
                dialog._on_step_finished(0, QProcess.ExitStatus.NormalExit)
                self.assertLoggedEqual('second step started', 2, start_process.call_count)
                dialog._on_step_finished(0, QProcess.ExitStatus.NormalExit)

            self.assertLoggedEqual('environment verified once all steps finish', 1, steps_finished.call_count)
            self.assertLoggedFalse('installation not failed', dialog._installation_failed)
        finally:
            self._dispose(dialog)
