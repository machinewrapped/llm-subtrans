import tempfile
from pathlib import Path
from unittest.mock import patch

from tests.GuiTestSupport import ConfigureOffscreenPlatform

ConfigureOffscreenPlatform()

from PySide6.QtWidgets import QApplication

from GuiSubtrans.Widgets.TorchSetupDialog import TorchSetupDialog
from PySubtrans.Helpers.TestCases import LoggedTestCase
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
            self.assertLoggedEqual('CPU fallback action', 'Install CPU-only Torch', dialog._next_button.text())
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
