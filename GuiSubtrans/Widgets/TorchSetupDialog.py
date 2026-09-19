"""Dialog for setting up a Torch installation for local transcription."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QProcess
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
from PySubtrans.Transcription.Torch.Validation import (
    CompareCompatibility,
    FindVenvPython,
    HasTorchPackage,
    ProbeVenvCompatibility,
)


# Approximate total disk usage (venv + torch + dependencies) by build variant.
_ESTIMATED_SIZE_CUDA = _("~5 GB")
_ESTIMATED_SIZE_ROCM = _("~3.5 GB")
_ESTIMATED_SIZE_CPU = _("~350 MB")
_ESTIMATED_SIZE_MPS = _("~450 MB")


# Answers for the "what GPU do you have?" fallback question
_GPU_VENDOR_OPTIONS : dict[str, HardwareDetection] = {
    _("NVIDIA"): HardwareDetection(
        description=_("NVIDIA selected -- install the NVIDIA driver before setting up Torch"),
        index_url=CPU_INDEX_URL,
        is_gpu=False,
        guidance=_("Install the latest NVIDIA driver for this GPU from nvidia.com, "
                   "restart the computer, and choose Set up Torch again."),
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
    """Step-by-step dialog that helps users choose and install a Torch environment."""

    def __init__(self, current_path : str = '', parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Set up Torch for Local Transcription"))
        self.setMinimumWidth(680)
        self.setMinimumHeight(600)

        self.chosen_path : str = ''
        self._process : QProcess|None = None
        self._hardware : HardwareDetection|None = DetectHardware()
        self._existing_path : str|None = None
        self._cpu_fallback_checkbox : QCheckBox|None = None
        self._current_page : int = 0
        self._installation_failed : bool = False

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

        title = QLabel(_("Step 1 of 3 - Choose how to provide Torch"))
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
        self._automatic_radio = QRadioButton(_("Create a new environment and install Torch"), install_group)
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
        """Build the page that reports the two installation subprocesses."""
        page = QWidget(self)
        page_layout = QVBoxLayout(page)
        title = QLabel(_("Step 3 of 3 - Installing Torch"))
        title.setStyleSheet("font-weight: bold;")
        page_layout.addWidget(title)
        self._step_status_label = QLabel(_("Preparing installation..."), page)
        self._step_status_label.setWordWrap(True)
        page_layout.addWidget(self._step_status_label)
        self._log_output = QTextEdit(page)
        self._log_output.setReadOnly(True)
        # Keep Windows paths intact in diagnostic output; wrapping at the drive
        # letter colon makes paths look malformed and harder to copy.
        self._log_output.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
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
                _("Install CPU-only Torch") if self._requires_cpu_confirmation() else _("Install Torch"))
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
            self._show_page(1)

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
                _("Install CPU-only Torch") if requires_confirmation else _("Install Torch"))
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
            self._existing_label.setText(
                _("Found an existing Torch installation at: {path}").format(path=existing)
            )
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

        self._install_error_label.clear()
        self._installation_failed = False
        self._step_status_label.setText(_("Step 1 of 2: Creating the private Python environment..."))
        self._log_output.clear()

        # Find a Python interpreter to create the venv with
        python = FindCompatiblePython()
        if not python:
            self._install_error_label.setText(_("Python 3.10 or newer is required. Install Python, then try again."))
            return False

        self._target_dir = target_dir
        self._log(_("Creating virtual environment at {path}...").format(path=target_dir))
        self._run_step_create_venv(python, target_dir)
        return True

    def _start_process(self, program : str, arguments : list[str], on_finished : Callable[[int, QProcess.ExitStatus], None]) -> None:
        """Run an installer subprocess with merged output and a completion handler."""
        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._process.readyReadStandardOutput.connect(self._on_process_output)
        self._process.finished.connect(on_finished)
        self._process.start(program, arguments)

    def _run_step_create_venv(self, python : str, target_dir : str) -> None:
        """Step 1: Create a venv at the target directory."""
        self._start_process(python, ['-m', 'venv', target_dir], self._on_venv_created)

    def _on_venv_created(self, exit_code : int, exit_status : QProcess.ExitStatus) -> None:
        """After venv creation, install torch."""
        if exit_code != 0 or exit_status != QProcess.ExitStatus.NormalExit:
            self._log(_("Error: Virtual environment creation failed (exit code {code}).").format(code=exit_code))
            self._installation_failed = True
            self._step_status_label.setText(_("Step 1 could not be completed. Check the log and try again."))
            self._show_page(2)
            return

        self._log(_("Virtual environment created successfully."))
        self._step_status_label.setText(_("Step 2 of 2: Installing the Torch build for your hardware..."))
        self._log(_("Installing Torch (this may take several minutes)..."))
        self._run_step_install_torch()

    def _run_step_install_torch(self) -> None:
        """Step 2: Install torch into the venv via pip."""
        scripts_dir = 'Scripts' if sys.platform == 'win32' else 'bin'
        pip = os.path.join(self._target_dir, scripts_dir, 'pip')

        args = ['install', 'torch']
        if self._hardware and self._hardware.index_url:
            args.extend(['--index-url', self._hardware.index_url])

        self._start_process(pip, args, self._on_torch_installed)

    def _on_torch_installed(self, exit_code : int, exit_status : QProcess.ExitStatus) -> None:
        """After torch install, validate the result."""
        if exit_code != 0 or exit_status != QProcess.ExitStatus.NormalExit:
            self._log(_("Error: Torch installation failed (exit code {code}). Check the output above for details.").format(code=exit_code))
            self._installation_failed = True
            self._step_status_label.setText(_("Step 2 could not be completed. Check the log and try again."))
            self._show_page(2)
            return

        self._log(_("Torch installed successfully."))
        self._step_status_label.setText(_("Installation finished. Verifying the Torch environment..."))
        if not self._validate_and_accept(self._target_dir):
            self._installation_failed = True
            self._step_status_label.setText(_("Torch could not be validated. Check the log and try again."))
            self._show_page(2)

    def _validate_and_accept(self, directory : str) -> bool:
        """Validate that the directory contains a usable torch installation.

        A missing Torch package is a hard error, since accepting it would only
        fail on restart.  An interpreter mismatch is a strong warning instead:
        the environment may still work, and if it does not the user needs to
        know what to change.  Returns whether the environment was accepted.
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
