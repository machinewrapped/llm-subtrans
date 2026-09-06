import logging
import os
import time

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from GuiSubtrans.Widgets.OptionsWidgets import CreateOptionWidget, OptionWidget
from PySubtrans.Helpers.Localization import _
from PySubtrans.Helpers.Time import TimedeltaToText
from PySubtrans.Options import Options
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleProject import SubtitleProject
from PySubtrans.Transcription.AudioExtractor import SUPPORTED_MEDIA_EXTENSIONS
from PySubtrans.Transcription.TranscriptionCoordinator import TranscriptionCoordinator
from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionSegment


class _TranscriptionWorker(QObject):
    """
    Runs transcription off the GUI thread and reports back via signals.
    """
    progressed = Signal(int, int)
    segmented = Signal(object)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, coordinator : TranscriptionCoordinator, media_path : str):
        super().__init__()
        self.coordinator : TranscriptionCoordinator = coordinator
        self.media_path : str = media_path

    @Slot()
    def run(self) -> None:
        """Transcribe the media file, emitting progress as chunks complete."""
        try:
            project = self.coordinator.CreateTranscriptionProject(
                self.media_path, None,
                lambda done, total: self.progressed.emit(done, total),
                lambda segment: self.segmented.emit(segment))
            self.finished.emit(project)
        except Exception as e:
            self.failed.emit(str(e))


def _format_duration(seconds : float) -> str:
    """
    Format an elapsed-time estimate as m:ss.
    """
    total = max(0, int(seconds))
    return f"{total // 60}:{total % 60:02d}"


class TranscriptionDialog(QDialog):
    """
    App-modal dialog for transcribing media to a translation-ready project.

    The dialog owns its worker thread: the main window stays blocked while
    transcription runs, and accepting the dialog hands a SubtitleProject to
    the existing translation workflow (same as loading a source subtitle).
    """
    def __init__(self, options : Options, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Transcribe Media"))
        self.setModal(True)
        self.setMinimumHeight(560)

        self.global_options : Options = options
        self.coordinator : TranscriptionCoordinator|None = None
        self.thread : QThread|None = None
        self.project : SubtitleProject|None = None
        self.media_path : str|None = None
        self.provider : TranscriptionProvider|None = None
        self.provider_fields : dict[str, OptionWidget] = {}
        self._phase : str = "setup"
        self._run_started : float = 0.0
        self._chunks_done : int = 0
        self._chunks_total : int = 0
        self._last_span : str = ""

        self._build_form()
        self._refresh_providers()
        self._show_setup()

    @property
    def provider_name(self) -> str:
        """Currently selected transcription provider."""
        return str(self.provider_combo.currentText() or "")

    def _build_form(self) -> None:
        layout = QVBoxLayout(self)

        self.splitter = QSplitter(self)
        layout.addWidget(self.splitter, 1)

        self.left_pane = QWidget(self.splitter)
        left_layout = QVBoxLayout(self.left_pane)
        left_layout.setContentsMargins(0, 0, 0, 0)

        form = QFormLayout()
        left_layout.addLayout(form)

        file_row = QHBoxLayout()
        self.file_edit = QLineEdit(self)
        self.file_edit.setPlaceholderText(_("Select a video or audio file..."))
        self.file_edit.textChanged.connect(self._on_file_changed)
        browse_button = QPushButton(_("Browse..."), self)
        browse_button.clicked.connect(self._browse_file)
        file_row.addWidget(self.file_edit)
        file_row.addWidget(browse_button)
        form.addRow(_("Media file"), file_row)

        self.track_combo = QComboBox(self)
        form.addRow(_("Audio track"), self.track_combo)

        self.provider_combo = QComboBox(self)
        self.provider_combo.currentTextChanged.connect(self._on_provider_changed)
        form.addRow(_("Provider"), self.provider_combo)

        self.provider_form = QFormLayout()
        form.addRow(self.provider_form)

        self.min_chunk_spin = QDoubleSpinBox(self)
        self.min_chunk_spin.setRange(1.0, 600.0)
        self.min_chunk_spin.setValue(8.0)
        self.min_chunk_spin.setSuffix(_(" s"))
        self.min_chunk_spin.setToolTip(_("Provider-recommended default; reselecting the provider restores it"))
        form.addRow(_("Min chunk length"), self.min_chunk_spin)

        self.max_chunk_spin = QDoubleSpinBox(self)
        self.max_chunk_spin.setRange(10.0, 1800.0)
        self.max_chunk_spin.setValue(60.0)
        self.max_chunk_spin.setSuffix(_(" s"))
        self.max_chunk_spin.setToolTip(_("Provider-recommended default; reselecting the provider restores it"))
        form.addRow(_("Max chunk length"), self.max_chunk_spin)

        self.align_check = QCheckBox(_("Request word timestamps for line timings"), self)
        self.align_check.setToolTip(_("Engines without timestamp support fall back to chunk-level lines"))
        self.align_check.setChecked(True)
        form.addRow(self.align_check)
        left_layout.addStretch(1)

        self.results_view = QTextEdit(self.splitter)
        self.results_view.setReadOnly(True)
        self.results_view.setPlaceholderText(_("Transcribed lines will appear here..."))

        self.splitter.addWidget(self.left_pane)
        self.splitter.addWidget(self.results_view)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([380, 520])

        self.status_label = QLabel(_("Select a media file to begin."), self)
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        button_row = QHBoxLayout()
        self.transcribe_button = QPushButton(_("Transcribe"), self)
        self.transcribe_button.clicked.connect(self._start_transcription)
        self.abort_button = QPushButton(_("Abort"), self)
        self.abort_button.clicked.connect(self._abort_transcription)
        self.back_button = QPushButton(_("Back to Settings"), self)
        self.back_button.clicked.connect(self._show_setup)
        button_row.addWidget(self.transcribe_button)
        button_row.addWidget(self.abort_button)
        button_row.addWidget(self.back_button)
        layout.addLayout(button_row)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Open | QDialogButtonBox.StandardButton.Close, self)
        self.button_box.button(QDialogButtonBox.StandardButton.Open).setText(_("Open as Project"))
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def _refresh_providers(self) -> None:
        self.provider_combo.clear()
        try:
            names = sorted(TranscriptionProvider.get_providers())
        except Exception as e:
            logging.error(_("Unable to load transcription providers: {error}").format(error=str(e)))
            names = []
        self.provider_combo.addItems(names)
        if names:
            self._on_provider_changed(names[0])

    def _current_provider(self) -> TranscriptionProvider|None:
        name = self.provider_name
        if not name:
            return None
        try:
            saved = TranscriptionCoordinator.ResolveProviderSettings(name, SettingsType(), self.global_options)
            return TranscriptionProvider.create_provider(name, saved)
        except Exception as e:
            logging.error(_("Unable to create transcription provider: {error}").format(error=str(e)))
            return None

    def _on_provider_changed(self, name : str) -> None:
        self.provider = self._current_provider()
        self._rebuild_provider_form()
        if self.provider is not None:
            # Chunk bounds follow the provider until the user overrides them
            self.min_chunk_spin.setValue(self.provider.recommended_min_chunk_seconds)
            self.max_chunk_spin.setValue(self.provider.recommended_max_chunk_seconds)

    def _rebuild_provider_form(self) -> None:
        """
        Render the selected provider's own settings schema so the dialog
        never shows options a provider does not have.
        """
        while self.provider_form.rowCount():
            self.provider_form.removeRow(0)

        self.provider_fields = {}
        if self.provider is None:
            return

        try:
            schema = self.provider.GetOptions(self.provider.settings)
        except Exception as e:
            logging.error(_("Unable to load provider options: {error}").format(error=str(e)))
            return

        for key, (key_type, tooltip) in schema.items():
            field = CreateOptionWidget(key, self.provider.settings.get(key), key_type, tooltip=tooltip)
            self.provider_fields[key] = field
            self.provider_form.addRow(_(key), field)

    def _on_file_changed(self, path : str) -> None:
        self.media_path = path.strip() or None
        self.track_combo.clear()
        self.project = None
        if self.media_path and os.path.isfile(self.media_path):
            self._load_tracks()
        if self._phase == "setup":
            self.transcribe_button.setEnabled(bool(self.media_path))
        self.progress_bar.setValue(0)
        self.results_view.clear()

    def _browse_file(self) -> None:
        wildcards = ' '.join(f'*{ext}' for ext in SUPPORTED_MEDIA_EXTENSIONS)
        filters = f"{_('Media files')} ({wildcards});;{_('All Files')} (*)"
        filepath, _selected_filter = QFileDialog.getOpenFileName(parent=self, caption=_("Select Media File"), filter=filters)
        if filepath:
            self.file_edit.setText(filepath)

    def _load_tracks(self) -> None:
        if self.provider is None or not self.media_path:
            return
        try:
            coordinator = TranscriptionCoordinator(self.provider, SettingsType())
            tracks = coordinator.CheckRequirements(self.media_path)
            for track in tracks:
                self.track_combo.addItem(str(track), track.index)
            self.status_label.setText(_("Found {} audio track(s).").format(len(tracks)))
        except Exception as e:
            self.status_label.setText(_("Unable to read media: {error}").format(error=str(e)))

    def _build_coordinator(self) -> TranscriptionCoordinator|None:
        provider = self.provider
        if provider is None:
            return None
        for key, field in self.provider_fields.items():
            provider.settings[key] = field.GetValue()
        if not provider.ValidateSettings():
            self.status_label.setText(provider.validation_message or _("Invalid provider settings"))
            return None
        client = provider.GetTranscriptionClient(SettingsType())
        if not client.supports_timestamps:
            self.status_label.setText(_(
                "'{}' cannot provide subtitle timings, so transcription "
                "would produce no usable subtitles."
            ).format(provider.name))
            return None
        settings = SettingsType({
            'audio_track': self.track_combo.currentData() or 0,
            'language': provider.settings.get_str('language'),
            'min_chunk_seconds': self.min_chunk_spin.value(),
            'max_chunk_seconds': self.max_chunk_spin.value(),
            'transcription_align': self.align_check.isChecked(),
        })
        return TranscriptionCoordinator(provider, settings)

    def _start_transcription(self) -> None:
        if not self.media_path or not os.path.isfile(self.media_path):
            self.status_label.setText(_("Select a valid media file first."))
            return
        coordinator = self._build_coordinator()
        if coordinator is None:
            return
        self.coordinator = coordinator
        self.project = None
        self.results_view.clear()
        self._run_started = time.monotonic()
        self._chunks_done = 0
        self._chunks_total = 0
        self._last_span = ""
        self.worker = _TranscriptionWorker(coordinator, self.media_path)
        self.thread = QThread(self)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progressed.connect(self._on_progress)
        self.worker.segmented.connect(self._on_segment)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self._show_results(True)
        self.status_label.setText(_("Transcribing..."))
        self.thread.start()

    def _abort_transcription(self) -> None:
        if self.coordinator is not None:
            self.coordinator.Abort()
            self.status_label.setText(_("Aborting..."))

    @Slot(int, int)
    def _on_progress(self, done : int, total : int) -> None:
        self._chunks_done = done
        self._chunks_total = total
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(done)
        self._update_run_status()

    @Slot(object)
    def _on_segment(self, segment : TranscriptionSegment) -> None:
        """Append each transcribed line to the results pane as it completes."""
        start = TimedeltaToText(segment.start) or ""
        end = TimedeltaToText(segment.end) or ""
        self._last_span = f"{start} --> {end}"
        speaker = f"[{segment.speaker}] " if segment.speaker else ""
        self.results_view.append(f"[{self._last_span}] {speaker}{segment.text}")
        scrollbar = self.results_view.verticalScrollBar()
        if scrollbar is not None:
            scrollbar.setValue(scrollbar.maximum())
        self._update_run_status()

    def _update_run_status(self) -> None:
        """
        Meaningful run status: position, current span, elapsed time and
        effective transcription speed.
        """
        elapsed = max(0.0, time.monotonic() - self._run_started) if self._run_started else 0.0
        status = _("Transcribed chunk {done}/{total}").format(done=self._chunks_done, total=self._chunks_total)
        if self._last_span:
            status += f" [{self._last_span}]"
        status += _(" (elapsed {})").format(_format_duration(elapsed))
        if elapsed > 5.0 and self._chunks_done > 0 and self._chunks_total > 0:
            fraction = self._chunks_done / self._chunks_total
            if fraction > 0.02:
                remaining = elapsed / fraction - elapsed
                status += _(" (about {} left)").format(_format_duration(remaining))
        self.status_label.setText(status)

    @Slot(object)
    def _on_finished(self, project : SubtitleProject) -> None:
        self.project = project
        self._save_provider_settings()
        count = project.subtitles.linecount if project.subtitles else 0
        if self.coordinator is not None and self.coordinator.aborted:
            self.status_label.setText(_("Aborted - partial results ({} lines).").format(count))
        else:
            self.status_label.setText(_("Transcribed {} lines.").format(count))
        self.progress_bar.setValue(self.progress_bar.maximum())
        self._show_results(False)

    @Slot(str)
    def _on_failed(self, message : str) -> None:
        logging.error(_("Transcription failed: {error}").format(error=message))
        self.status_label.setText(_("Transcription failed: {error}").format(error=message))
        self._show_results(False)

    def _save_provider_settings(self) -> None:
        name = self.provider_name
        if not name or self.coordinator is None:
            return
        try:
            self.global_options.InitialiseProviderSettings(
                TranscriptionCoordinator.SettingsKey(name), self.coordinator.provider.settings)
            self.global_options.SaveSettings()
        except Exception as e:
            logging.warning(_("Unable to save transcription settings: {error}").format(error=str(e)))

    def _show_setup(self) -> None:
        """
        Setup phase: full-width settings, no results or progress widgets.
        """
        self._phase = "setup"
        self.setMinimumWidth(560)
        self.left_pane.setVisible(True)
        self.results_view.setVisible(False)
        self.progress_bar.setVisible(False)
        self.transcribe_button.setVisible(True)
        self.transcribe_button.setEnabled(bool(self.media_path))
        self.abort_button.setVisible(False)
        self.back_button.setVisible(False)
        open_button = self.button_box.button(QDialogButtonBox.StandardButton.Open)
        if open_button is not None:
            open_button.setEnabled(self.project is not None)

    def _show_results(self, running : bool) -> None:
        """
        Run/finish phase: full-width results, settings put away.
        """
        self._phase = "running" if running else "done"
        self.setMinimumWidth(920)
        self.left_pane.setVisible(False)
        self.results_view.setVisible(True)
        self.progress_bar.setVisible(True)
        self.transcribe_button.setVisible(False)
        self.abort_button.setVisible(running)
        self.back_button.setVisible(not running)
        open_button = self.button_box.button(QDialogButtonBox.StandardButton.Open)
        if open_button is not None:
            open_button.setEnabled(not running and self.project is not None)

    def closeEvent(self, event) -> None:
        """Abort any running transcription when the dialog closes."""
        if self.coordinator is not None and self.thread is not None and self.thread.isRunning():
            self.coordinator.Abort()
            self.thread.quit()
            self.thread.wait(5000)
        super().closeEvent(event)
