import subprocess
import sys
from unittest.mock import patch

from tests.GuiTestSupport import ConfigureOffscreenPlatform

ConfigureOffscreenPlatform()

from PySide6.QtWidgets import QApplication

from GuiSubtrans.Widgets.TorchSetupDialog import TorchSetupDialog, _python_meets_minimum
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

    def test_cpu_fallback_requires_explicit_confirmation(self) -> None:
        """A detected GPU without a driver cannot silently install CPU Torch."""
        hardware = HardwareDetection(
            'NVIDIA GPU detected, but its driver is unavailable',
            'https://download.pytorch.org/whl/cpu',
            False,
            'Install the latest NVIDIA driver, restart, and try again.',
            hardware_detected=True,
        )
        with patch('GuiSubtrans.Widgets.TorchSetupDialog.DetectHardware', return_value=hardware), \
                patch('GuiSubtrans.Widgets.TorchSetupDialog._find_existing_torch', return_value=None):
            dialog = TorchSetupDialog()

        try:
            dialog._show_page(1)
            self.assertLoggedFalse('CPU install requires confirmation', dialog._next_button.isEnabled())
            self.assertLoggedEqual('CPU fallback action', 'Install CPU-only Torch', dialog._next_button.text())
            if dialog._cpu_fallback_checkbox is not None:
                self.assertLoggedFalse('CPU fallback is initially unchecked', dialog._cpu_fallback_checkbox.isChecked())
                dialog._cpu_fallback_checkbox.setChecked(True)
                self.assertLoggedTrue('CPU install enabled after confirmation', dialog._next_button.isEnabled())
        finally:
            dialog.deleteLater()
            self.application.processEvents()

    def test_manual_path_enables_continue_and_is_used_directly(self) -> None:
        """Selecting the manual-locate option validates the typed path without an install step."""
        with patch('GuiSubtrans.Widgets.TorchSetupDialog._find_existing_torch', return_value=None):
            dialog = TorchSetupDialog()

        try:
            dialog._manual_radio.setChecked(True)
            self.assertLoggedFalse('continue disabled with empty manual path', dialog._next_button.isEnabled())

            dialog._manual_path_field.setText('/some/torch/env')
            self.assertLoggedTrue('continue enabled once a manual path is entered', dialog._next_button.isEnabled())
            self.assertLoggedEqual('continue button label', 'Use this installation', dialog._next_button.text())

            with patch.object(dialog, '_validate_and_accept') as mock_validate:
                dialog._on_next()

            mock_validate.assert_called_once_with('/some/torch/env')
        finally:
            dialog.deleteLater()
            self.application.processEvents()

    def test_python_meets_minimum_accepts_current_interpreter(self) -> None:
        """The running interpreter (>=3.10, per project requirements) passes the floor check."""
        self.assertLoggedTrue('current interpreter satisfies torch minimum', _python_meets_minimum(sys.executable))

    def test_python_meets_minimum_rejects_old_version(self) -> None:
        """An interpreter reporting a version below 3.10 is rejected."""
        fake_result = subprocess.CompletedProcess(args=[], returncode=0, stdout='3.9\n')
        with patch('GuiSubtrans.Widgets.TorchSetupDialog.subprocess.run', return_value=fake_result):
            self.assertLoggedFalse('Python 3.9 does not satisfy the torch minimum', _python_meets_minimum('fake-python'))

    def test_python_meets_minimum_rejects_missing_interpreter(self) -> None:
        """A candidate that cannot be executed is rejected rather than raising."""
        with patch('GuiSubtrans.Widgets.TorchSetupDialog.subprocess.run', side_effect=OSError('not found')):
            self.assertLoggedFalse('missing interpreter is rejected', _python_meets_minimum('does-not-exist'))
