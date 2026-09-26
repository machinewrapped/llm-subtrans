"""Dialog for setting up the Torch environment and Qwen runtime for local transcription."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QProcess
from PySide6.QtGui import QTextOption
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from PySubtrans.Helpers.Localization import _
from PySubtrans.Helpers.Resources import GetAppDir
from PySubtrans.Transcription.Torch.Discovery import (
    DEFAULT_TORCH_DIR_NAME,
    ExpectedCompatibility,
    FindCompatiblePython,
    FindExistingTorch,
)
from PySubtrans.Transcription.Torch.Hardware import (
    CPU_INDEX_URL,
    DetectHardware,
    HardwareDetection,
    ROCM_INDEX_URL,  # pyright: ignore[reportUnusedImport] — only reached on Linux; false positive on Windows
)
from PySubtrans.Transcription.Torch.Runtime import TorchConfigOption
from PySubtrans.Transcription.Torch.QwenRuntime import (
    QWEN_ASR_REQUIREMENT,
    NeedsQwenRuntime,
    ReadQwenAsrDependencies,
)
from PySubtrans.Transcription.Torch.Validation import (
    CompareCompatibility,
    FindTorchSitePackages,
    FindVenvPython,
    HasTorchPackage,
    ProbeVenvCompatibility,
)


# Approximate total disk usage (venv + torch + Qwen runtime) by build variant.
_ESTIMATED_SIZE_CUDA = _("~5.5 GB")
_ESTIMATED_SIZE_ROCM = _("~4 GB")
_ESTIMATED_SIZE_CPU = _("~1 GB")
_ESTIMATED_SIZE_MPS = _("~1 GB")

# Approximate disk usage of the Qwen runtime on its own, when adding it to an existing environment
_ESTIMATED_SIZE_QWEN_RUNTIME = _("~600 MB")


@dataclass(frozen=True)
class _InstallStep:
    """One installer subprocess in the setup sequence."""
    status : str
    start_message : str
    success_message : str
    failure_message : str
    command : Callable[[], tuple[str, list[str]]|None]


# Answers for the "what GPU do you have?" fallback question
_GPU_VENDOR_OPTIONS : dict[str, HardwareDetection] = {
    _("NVIDIA"): HardwareDetection(
        description=_("NVIDIA selected -- install the NVIDIA driver before setting up Torch"),
        index_url=CPU_INDEX_URL,
        is_gpu=False,
        guidance=_("Install the latest NVIDIA driver for this GPU from nvidia.com, "
                   "restart the computer, and choose {button} again.").format(button=TorchConfigOption.label),
        hardware_detected=True,
        estimated_size=_ESTIMATED_SIZE_CPU,
    ),
    _("AMD"): HardwareDetection(
        description=_("AMD selected"),
        index_url=ROCM_INDEX_URL if sys.platform == 'linux' else CPU_INDEX_URL,
        is_gpu=sys.platform == 'linux',
        guidance='' if sys.platform == 'linux'
                 else _("PyTorch GPU support for AMD requires Linux with ROCm."),
        hardware_detected=sys.platform != 'linux',
        estimated_size=_ESTIMATED_SIZE_ROCM if sys.platform == 'linux' else _ESTIMATED_SIZE_CPU,
    ),
    _("Intel"): HardwareDetection(
        description=_("Intel selected"),
        index_url=CPU_INDEX_URL,
        is_gpu=False,
        guidance=_("PyTorch XPU support requires the Intel oneAPI toolkit (intel.com/oneapi)."),
        hardware_detected=True,
        estimated_size=_ESTIMATED_SIZE_CPU,
    ),
    _("No GPU / CPU only"): HardwareDetection(
        description=_("CPU selected -- transcription will work but will be significantly slower than with a GPU"),
        index_url=CPU_INDEX_URL,
        is_gpu=False,
        estimated_size=_ESTIMATED_SIZE_CPU,
    ),
}


class TorchSetupDialog(QDialog):
    """Step-by-step dialog that helps users choose or install an environment with Torch and the Qwen runtime."""

    def __init__(self, current_path : str = '', parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Set Up Local Transcription"))
        self.setMinimumWidth(680)
        self.setMinimumHeight(600)

        self.chosen_path : str = ''
        self._process : QProcess|None = None
        self._hardware : HardwareDetection|None = DetectHardware()
        self._existing_path : str|None = None
        self._cpu_fallback_checkbox : QCheckBox|None = None
        self._current_page : int = 0
        self._installation_failed : bool = False
        self._target_dir : str = ''
        self._steps : list[_InstallStep] = []
        self._step_index : int = 0

        # The page Back returns to after a failed installation
        self._retry_page : int = 1

        self._build_ui(current_path)
        self._scan_for_existing_torch()

    def _build_ui(self, current_path : str) -> None:
        """Construct the four-page setup flow."""
        layout = QVBoxLayout(self)
        self._page_stack = QStackedWidget(self)
        layout.addWidget(self._page_stack, 1)

        self._build_choice_page()
        self._build_install_page(current_path)
        self._build_progress_page()

        self._button_box = QDialogButtonBox(self)
        self._back_button = QPushButton(_("Back"), self)
        self._next_button = QPushButton(_("Continue"), self)
        self._button_box.addButton(self._back_button, QDialogButtonBox.ButtonRole.ActionRole)
        self._button_box.addButton(self._next_button, QDialogButtonBox.ButtonRole.ActionRole)
        self._cancel_button = self._button_box.addButton(QDialogButtonBox.StandardButton.Cancel)
        self._back_button.clicked.connect(self._on_back)
        self._next_button.clicked.connect(self._on_next)
        self._button_box.rejected.connect(self.reject)
        layout.addWidget(self._button_box)

        self._show_page(0)

    def _build_choice_page(self) -> None:
        """Build the first page where the user chooses one setup route."""
        page = QWidget(self)
        page_layout = QVBoxLayout(page)

        title = QLabel(_("Step 1 of 3 - Choose an environment for local transcription"))
        title.setStyleSheet("font-weight: bold;")
        page_layout.addWidget(title)
        page_layout.addWidget(QLabel(_("Choose one option, then click Continue. You will not need to complete both.")))

        self._existing_group = QGroupBox(_("Use an existing installation"), page)
        existing_layout = QVBoxLayout(self._existing_group)
        self._existing_radio = QRadioButton(_("Use the detected Torch environment"), self._existing_group)
        self._existing_radio.setEnabled(False)
        existing_layout.addWidget(self._existing_radio)
        self._existing_label = QLabel(_("Searching for an existing Torch installation..."), self._existing_group)
        self._existing_label.setWordWrap(True)
        existing_layout.addWidget(self._existing_label)

        self._manual_radio = QRadioButton(_("Locate an existing installation manually"), self._existing_group)
        existing_layout.addWidget(self._manual_radio)
        manual_row = QHBoxLayout()
        self._manual_path_field = QLineEdit(self._existing_group)
        self._manual_path_field.setPlaceholderText(_("Path to a Python virtual environment containing torch"))
        self._manual_path_field.textChanged.connect(self._on_choice_changed)
        manual_row.addWidget(self._manual_path_field)
        manual_browse_button = QPushButton(_("Browse..."), self._existing_group)
        manual_browse_button.clicked.connect(self._on_manual_browse)
        manual_row.addWidget(manual_browse_button)
        existing_layout.addLayout(manual_row)

        page_layout.addWidget(self._existing_group)

        install_group = QGroupBox(_("Install automatically"), page)
        install_layout = QVBoxLayout(install_group)
        self._automatic_radio = QRadioButton(_("Create a new environment and install Torch and the Qwen runtime"), install_group)
        self._automatic_radio.setChecked(True)
        install_layout.addWidget(self._automatic_radio)
        install_layout.addWidget(QLabel(_("The next page will ask where to create it and show the detected hardware.")))
        page_layout.addWidget(install_group)
        page_layout.addStretch(1)

        self._choice_button_group = QButtonGroup(self)
        self._choice_button_group.setExclusive(True)
        self._choice_button_group.addButton(self._existing_radio)
        self._choice_button_group.addButton(self._manual_radio)
        self._choice_button_group.addButton(self._automatic_radio)
        self._existing_radio.toggled.connect(self._on_choice_changed)
        self._manual_radio.toggled.connect(self._on_choice_changed)
        self._automatic_radio.toggled.connect(self._on_choice_changed)
        self._page_stack.addWidget(page)

    def _build_install_page(self, current_path : str) -> None:
        """Build the page for the automatic installation choices."""
        page = QWidget(self)
        page_layout = QVBoxLayout(page)

        title = QLabel(_("Step 2 of 3 - Choose the installation options"))
        title.setStyleSheet("font-weight: bold;")
        page_layout.addWidget(title)
        page_layout.addWidget(QLabel(_("Choose a folder for the new environment. Hardware detection selects the Torch build automatically.")))

        directory_group = QGroupBox(_("Installation folder"), page)
        directory_layout = QVBoxLayout(directory_group)
        dir_row = QHBoxLayout()
        default_path = current_path or os.path.join(GetAppDir(), DEFAULT_TORCH_DIR_NAME)
        self._dir_field = QLineEdit(default_path, directory_group)
        self._dir_field.setCursorPosition(0)
        self._dir_field.setToolTip(_("A new Python virtual environment will be created here."))
        dir_row.addWidget(self._dir_field)
        browse_button = QPushButton(_("Browse..."), directory_group)
        browse_button.clicked.connect(self._on_browse)
        dir_row.addWidget(browse_button)
        directory_layout.addLayout(dir_row)
        directory_layout.addWidget(QLabel(_("Use a new or empty folder; existing files will not be overwritten.")))
        self._install_error_label = QLabel('', directory_group)
        self._install_error_label.setWordWrap(True)
        directory_layout.addWidget(self._install_error_label)
        page_layout.addWidget(directory_group)

        hardware_group = QGroupBox(_("Detected hardware"), page)
        hardware_layout = QVBoxLayout(hardware_group)
        if self._hardware:
            self._hardware_label = QLabel(self._hardware.description, hardware_group)
            self._hardware_label.setWordWrap(True)
            hardware_layout.addWidget(self._hardware_label)

            if self._hardware.guidance:
                guidance_label = QLabel(self._hardware.guidance, hardware_group)
                guidance_label.setWordWrap(True)
                hardware_layout.addWidget(guidance_label)

            if not self._hardware.is_gpu:
                cpu_warning = QLabel(
                    _("GPU acceleration is strongly recommended. "
                      "See <a href=\"https://pytorch.org/get-started/locally/\">pytorch.org</a> "
                      "for hardware-specific instructions."),
                    hardware_group)
                cpu_warning.setWordWrap(True)
                cpu_warning.setOpenExternalLinks(True)
                hardware_layout.addWidget(cpu_warning)
        else:
            hardware_layout.addWidget(QLabel(_("GPU detection was inconclusive. Choose the closest option:"), hardware_group))
            self._gpu_combo = QComboBox(hardware_group)
            for vendor_label in _GPU_VENDOR_OPTIONS:
                self._gpu_combo.addItem(vendor_label)
            self._gpu_combo.setCurrentIndex(self._gpu_combo.count() - 1)
            self._gpu_combo.currentTextChanged.connect(self._on_gpu_vendor_changed)
            hardware_layout.addWidget(self._gpu_combo)
            self._vendor_guidance_label = QLabel('', hardware_group)
            self._vendor_guidance_label.setWordWrap(True)
            self._vendor_guidance_label.setOpenExternalLinks(True)
            hardware_layout.addWidget(self._vendor_guidance_label)
        page_layout.addWidget(hardware_group)

        size_text = self._hardware.estimated_size if self._hardware else ''
        self._size_label = QLabel(
            _("Estimated disk usage: {size}").format(size=size_text) if size_text else '',
            page)
        page_layout.addWidget(self._size_label)

        self._cpu_fallback_checkbox = QCheckBox(
            _("Install CPU-only Torch anyway (transcription will be slower)"), page)
        self._cpu_fallback_checkbox.setVisible(False)
        self._cpu_fallback_checkbox.toggled.connect(self._on_cpu_fallback_changed)
        page_layout.addWidget(self._cpu_fallback_checkbox)

        if self._hardware is None:
            self._on_gpu_vendor_changed(self._gpu_combo.currentText())
        else:
            self._update_cpu_fallback_choice()

        page_layout.addStretch(1)
        self._page_stack.addWidget(page)

    def _build_progress_page(self) -> None:
        """Build the page that reports the installation subprocesses."""
        page = QWidget(self)
        page_layout = QVBoxLayout(page)
        self._progress_title = QLabel(_("Step 3 of 3 - Installing Torch and the Qwen runtime"))
        self._progress_title.setStyleSheet("font-weight: bold;")
        page_layout.addWidget(self._progress_title)
        self._step_status_label = QLabel(_("Preparing installation..."), page)
        self._step_status_label.setWordWrap(True)
        page_layout.addWidget(self._step_status_label)
        self._log_output = QTextEdit(page)
        self._log_output.setReadOnly(True)
        # Wrap at the edge like a terminal rather than at word boundaries, which split Windows paths after the drive letter colon.
        # Soft wraps are not copied, so paths still paste intact.
        self._log_output.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self._log_output.setWordWrapMode(QTextOption.WrapMode.WrapAnywhere)
        self._log_output.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        page_layout.addWidget(self._log_output)
        self._page_stack.addWidget(page)


    def _show_page(self, page_index : int) -> None:
        """Show one setup page and configure only its relevant navigation buttons."""
        self._current_page = page_index
        self._page_stack.setCurrentIndex(page_index)

        self._back_button.setVisible(page_index == 1 or (page_index == 2 and self._installation_failed))
        self._back_button.setEnabled(page_index == 1 or (page_index == 2 and self._installation_failed))
        self._next_button.setVisible(page_index in (0, 1))
        self._next_button.setEnabled(page_index in (0, 1))

        if page_index == 0:
            self._on_choice_changed()
        elif page_index == 1:
            self._update_cpu_fallback_choice()
            self._next_button.setText(
                _("Install with CPU-only Torch") if self._requires_cpu_confirmation() else _("Install"))
            self._next_button.setEnabled(self._can_start_install())

    def _on_choice_changed(self) -> None:
        """Update the first-page action to match the selected setup route."""
        if self._current_page != 0:
            return

        if self._existing_radio.isChecked():
            self._next_button.setText(_("Use existing installation"))
            self._next_button.setEnabled(bool(self._existing_path))
        elif self._manual_radio.isChecked():
            self._next_button.setText(_("Use this installation"))
            self._next_button.setEnabled(bool(self._manual_path_field.text().strip()))
        else:
            self._next_button.setText(_("Choose installation options"))
            self._next_button.setEnabled(True)

    def _on_next(self) -> None:
        """Advance the guided flow or start the selected installation."""
        if self._current_page == 0:
            if self._existing_radio.isChecked():
                if self._existing_path:
                    self._validate_and_accept(self._existing_path)
            elif self._manual_radio.isChecked():
                manual_path = self._manual_path_field.text().strip()
                if manual_path:
                    self._validate_and_accept(manual_path)
            else:
                self._show_page(1)
            return

        if self._current_page == 1:
            if self._on_install():
                self._show_page(2)

    def _on_back(self) -> None:
        """Return to the previous setup choice when no installation is running."""
        if self._current_page == 1:
            self._show_page(0)
        elif self._current_page == 2 and self._installation_failed:
            self._show_page(self._retry_page)

    def _requires_cpu_confirmation(self) -> bool:
        """Whether a detected GPU lacks a usable Torch acceleration backend."""
        return bool(self._hardware and self._hardware.hardware_detected and not self._hardware.is_gpu)

    def _can_start_install(self) -> bool:
        """Whether the current hardware choice permits automatic installation."""
        return not self._requires_cpu_confirmation() or bool(
            self._cpu_fallback_checkbox and self._cpu_fallback_checkbox.isChecked())

    def _update_cpu_fallback_choice(self) -> None:
        """Show the explicit CPU fallback choice when GPU setup is unavailable."""
        if self._cpu_fallback_checkbox is None:
            return

        requires_confirmation = self._requires_cpu_confirmation()
        self._cpu_fallback_checkbox.setVisible(requires_confirmation)
        if not requires_confirmation:
            self._cpu_fallback_checkbox.setChecked(False)

        if hasattr(self, '_next_button') and self._current_page == 1:
            self._next_button.setText(
                _("Install with CPU-only Torch") if requires_confirmation else _("Install"))
            self._next_button.setEnabled(self._can_start_install())

    def _on_cpu_fallback_changed(self, checked : bool) -> None:
        """Update installation navigation after an explicit CPU fallback choice."""
        del checked
        self._update_cpu_fallback_choice()

    def _on_gpu_vendor_changed(self, vendor_text : str) -> None:
        """Update hardware selection when the user picks a GPU vendor."""
        selection = _GPU_VENDOR_OPTIONS.get(vendor_text)
        if selection:
            self._hardware = selection
            self._vendor_guidance_label.setText(selection.guidance)
            if hasattr(self, '_size_label'):
                self._size_label.setText(
                    _("Estimated disk usage: {size}").format(size=selection.estimated_size)
                    if selection.estimated_size else '')
        else:
            self._hardware = None
        self._update_cpu_fallback_choice()

    def _scan_for_existing_torch(self) -> None:
        """Look for a torch installation already on the system."""
        existing = FindExistingTorch()
        if existing:
            description = _("Found an existing Torch installation at: {path}").format(path=existing)
            if NeedsQwenRuntime(Path(existing)):
                description += "\n" + _("It does not include the Qwen runtime yet, which will be installed into it ({size}).").format(size=_ESTIMATED_SIZE_QWEN_RUNTIME)
            self._existing_label.setText(description)
            self._existing_path = existing
            self._existing_radio.setEnabled(True)
            self._existing_radio.setChecked(True)
            self._automatic_radio.setChecked(False)
        else:
            self._existing_label.setText(_("No existing Torch installation found on this system."))
            self._existing_path = None
            self._existing_radio.setEnabled(False)

    def _on_browse(self) -> None:
        """Open a directory picker."""
        directory = QFileDialog.getExistingDirectory(
            self, _("Select Torch Installation Directory"), self._dir_field.text()
        )
        if directory:
            self._dir_field.setText(directory)

    def _on_manual_browse(self) -> None:
        """Open a directory picker for manually locating an existing installation."""
        directory = QFileDialog.getExistingDirectory(
            self, _("Select Torch Installation Directory"), self._manual_path_field.text()
        )
        if directory:
            self._manual_path_field.setText(directory)

    def _on_install(self) -> bool:
        """Start the automatic installation and return whether it was started."""
        if not self._can_start_install():
            self._install_error_label.setText(
                _("Install or update the GPU driver, then run setup again, or select Install CPU-only Torch anyway."))
            return False

        target_dir = self._dir_field.text().strip()
        if not target_dir:
            self._install_error_label.setText(_("Choose an installation folder before continuing."))
            return False

        # Find a Python interpreter to create the venv with
        python = FindCompatiblePython()
        if not python:
            self._install_error_label.setText(_("Python 3.10 or newer is required. Install Python, then try again."))
            return False

        self._install_error_label.clear()
        self._target_dir = target_dir
        self._retry_page = 1
        self._progress_title.setText(_("Step 3 of 3 - Installing Torch and the Qwen runtime"))

        steps = [self._create_venv_step(python), self._install_torch_step(), *self._qwen_runtime_steps()]
        self._run_steps(steps)
        return True

    def _offer_qwen_runtime_install(self, directory : str) -> bool:
        """
        Offer to install the Qwen runtime into a Torch environment that lacks it, such as one set up for an earlier version.
        Returns whether the installation was started.
        """
        root = Path(directory).expanduser()
        if FindVenvPython(root) is None:
            QMessageBox.warning(
                self,
                _("Qwen Runtime Not Found"),
                _("The Torch environment at:\n{path}\n\n"
                  "does not include the Qwen runtime, and has no Python interpreter to install it with.\n\n"
                  "Select a virtual environment, or use the automatic install.").format(path=directory),
            )
            return False

        answer = QMessageBox.question(
            self,
            _("Install Qwen Runtime"),
            _("The Torch environment at:\n{path}\n\n"
              "does not include the Qwen runtime that local transcription needs.\n\n"
              "Install it into this environment now? It needs about {size} of disk space.").format(path=directory, size=_ESTIMATED_SIZE_QWEN_RUNTIME),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False

        self._target_dir = directory
        self._retry_page = 0
        self._progress_title.setText(_("Installing the Qwen runtime"))
        self._run_steps(self._qwen_runtime_steps())
        self._show_page(2)
        return True

    def _create_venv_step(self, python : str) -> _InstallStep:
        """Create a venv at the target directory."""
        target_dir = self._target_dir
        return _InstallStep(
            status=_("Creating the private Python environment..."),
            start_message=_("Creating virtual environment at {path}...").format(path=target_dir),
            success_message=_("Virtual environment created successfully."),
            failure_message=_("Error: Virtual environment creation failed (exit code {code})."),
            command=lambda: (python, ['-m', 'venv', '--upgrade-deps', target_dir]),
        )

    def _install_torch_step(self) -> _InstallStep:
        """Install the Torch build for the detected hardware into the venv."""
        arguments = ['install', 'torch']
        if self._hardware and self._hardware.index_url:
            arguments.extend(['--index-url', self._hardware.index_url])

        return _InstallStep(
            status=_("Installing the Torch build for your hardware..."),
            start_message=_("Installing Torch (this may take several minutes)..."),
            success_message=_("Torch installed successfully."),
            failure_message=_("Error: Torch installation failed (exit code {code}). Check the output above for details."),
            command=lambda: self._pip_command(arguments),
        )

    def _qwen_runtime_steps(self) -> list[_InstallStep]:
        """
        Install the Qwen runtime into the venv.
        qwen-asr goes in without its dependencies, then the dependencies it declares follow, minus those only its demo apps use.
        """
        return [
            _InstallStep(
                status=_("Installing qwen-asr..."),
                start_message=_("Installing {requirement}...").format(requirement=QWEN_ASR_REQUIREMENT),
                success_message=_("qwen-asr installed successfully."),
                failure_message=_("Error: qwen-asr installation failed (exit code {code}). Check the output above for details."),
                command=lambda: self._pip_command(['install', '--no-deps', QWEN_ASR_REQUIREMENT]),
            ),
            _InstallStep(
                status=_("Installing the Qwen runtime dependencies..."),
                start_message=_("Installing the Qwen runtime dependencies (this may take several minutes)..."),
                success_message=_("Qwen runtime dependencies installed successfully."),
                failure_message=_("Error: Qwen runtime dependency installation failed (exit code {code}). Check the output above for details."),
                command=self._qwen_dependencies_command,
            ),
        ]

    def _qwen_dependencies_command(self) -> tuple[str, list[str]]|None:
        """Build the pip command for the dependencies of the qwen-asr just installed into the venv."""
        site_packages = FindTorchSitePackages(Path(self._target_dir).expanduser())
        dependencies = ReadQwenAsrDependencies([str(site_packages)]) if site_packages else None
        if dependencies is None:
            self._log(_("Error: The qwen-asr package metadata could not be found in {path}.").format(path=self._target_dir))
            return None

        # pip would report the demo app packages left out as missing dependencies of qwen-asr, which reads as a failed install
        return self._pip_command(['install', '--no-warn-conflicts', *dependencies])

    def _pip_command(self, arguments : list[str]) -> tuple[str, list[str]]|None:
        """Build a pip command that runs with the target venv's interpreter, or None if it has none."""
        venv_python = FindVenvPython(Path(self._target_dir).expanduser())
        if venv_python is None:
            self._log(_("Error: No Python interpreter was found in {path}.").format(path=self._target_dir))
            return None

        return str(venv_python), ['-m', 'pip', *arguments]

    def _run_steps(self, steps : list[_InstallStep]) -> None:
        """Run the installer steps in sequence, stopping at the first failure."""
        self._steps = steps
        self._step_index = 0
        self._installation_failed = False
        self._log_output.clear()
        self._run_next_step()

    def _run_next_step(self) -> None:
        """Start the next installer step, or verify the environment once all have finished."""
        if self._step_index >= len(self._steps):
            self._on_steps_finished()
            return

        step = self._steps[self._step_index]
        self._step_status_label.setText(_("Part {number} of {total}: {status}").format(
            number=self._step_index + 1, total=len(self._steps), status=step.status))
        self._log(step.start_message)

        command = step.command()
        if command is None:
            self._fail_step()
            return

        program, arguments = command
        self._start_process(program, arguments, self._on_step_finished)

    def _on_step_finished(self, exit_code : int, exit_status : QProcess.ExitStatus) -> None:
        """Advance to the next installer step, or stop if this one failed."""
        step = self._steps[self._step_index]
        if exit_code != 0 or exit_status != QProcess.ExitStatus.NormalExit:
            self._log(step.failure_message.format(code=exit_code))
            self._fail_step()
            return

        self._log(step.success_message)
        self._step_index += 1
        self._run_next_step()

    def _fail_step(self) -> None:
        """Report that the current installer step failed and let the user go back."""
        self._installation_failed = True
        self._step_status_label.setText(_("Part {number} could not be completed. Check the log and try again.").format(number=self._step_index + 1))
        self._show_page(2)

    def _on_steps_finished(self) -> None:
        """Validate the environment once every installer step has succeeded."""
        self._step_status_label.setText(_("Installation finished. Verifying the Torch environment..."))

        if NeedsQwenRuntime(Path(self._target_dir).expanduser()):
            self._log(_("Error: The Qwen runtime could not be found in {path} after installation.").format(path=self._target_dir))
        elif self._validate_and_accept(self._target_dir):
            return

        self._installation_failed = True
        self._step_status_label.setText(_("Torch could not be validated. Check the log and try again."))
        self._show_page(2)

    def _start_process(self, program : str, arguments : list[str], on_finished : Callable[[int, QProcess.ExitStatus], None]) -> None:
        """Run an installer subprocess with merged output and a completion handler."""
        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._process.readyReadStandardOutput.connect(self._on_process_output)
        self._process.finished.connect(on_finished)
        self._process.start(program, arguments)

    def _validate_and_accept(self, directory : str) -> bool:
        """Validate that the directory contains a usable torch installation.

        A missing Torch package is a hard error, since accepting it would only
        fail on restart.  A missing Qwen runtime is offered for installation,
        and the environment is validated again once it is installed.  An
        interpreter mismatch is a strong warning instead: the environment may
        still work, and if it does not the user needs to know what to change.
        Returns whether the environment was accepted.
        """
        root = Path(directory).expanduser()

        if not HasTorchPackage(root):
            QMessageBox.warning(
                self,
                _("Torch Not Found"),
                _("No Torch package could be found in:\n{path}\n\n"
                  "Select a virtual environment that contains Torch, or use the automatic install.").format(path=directory),
            )
            return False

        if NeedsQwenRuntime(root):
            self._offer_qwen_runtime_install(directory)
            return False

        self._log(_("Validated Torch installation at {path}.").format(path=directory))

        warning = self._compatibility_warning(root)
        if warning:
            QMessageBox.warning(self, _("Torch Compatibility Warning"), warning)

        self.chosen_path = directory

        QMessageBox.information(
            self,
            _("Restart Required"),
            _("Torch environment selected at:\n{path}\n\n"
              "The application needs to be restarted for the change to take effect.").format(path=directory),
        )
        self.accept()
        return True

    def _compatibility_warning(self, root : Path) -> str|None:
        """Describe why the selected venv may be incompatible, or None if it matches."""
        try:
            compatibility = ExpectedCompatibility()
        except (ValueError, RuntimeError) as error:
            return _("The compatibility information for this build could not be read: {error}").format(error=error)

        if compatibility is None:
            return None

        venv_python = FindVenvPython(root)
        if venv_python is None:
            # Packaged builds expect a complete venv; a source run may point at
            # a bare site-packages directory with no interpreter to probe.
            if getattr(sys, 'frozen', False):
                return _("The selected environment has no Python interpreter, so its compatibility could not be verified.")
            return None

        actual = ProbeVenvCompatibility(venv_python)
        if actual is None:
            return _("The selected environment's Python interpreter could not be checked.")

        mismatches = CompareCompatibility(actual, compatibility)
        if not mismatches:
            self._log(_("ABI compatibility check passed."))
            return None

        return _("The selected Torch environment may be incompatible with this application:\n{details}\n\n"
                 "Torch is loaded into this application, so its Python ABI, OS, architecture and pointer width "
                 "should match the build. If Torch fails to load, install a matching environment.").format(
                     details="\n".join(mismatches))

    def reject(self) -> None:
        """Stop an active installer before closing the dialog."""
        if self._process is not None and self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.kill()
            self._process.waitForFinished(1000)
        super().reject()

    def _on_process_output(self) -> None:
        """Append process stdout/stderr to the log widget."""
        if self._process:
            text = bytes(self._process.readAllStandardOutput().data()).decode('utf-8', errors='replace')
            self._log_output.append(text.rstrip())

    def _log(self, message : str) -> None:
        """Append a message to the log widget."""
        self._log_output.append(message)
        logging.info(message)
