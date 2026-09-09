import logging
import os
import time
from typing import Any, Callable, cast

from PySide6.QtCore import QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from GuiSubtrans.Commands.TranscribeMediaCommand import TranscribeMediaCommand
from GuiSubtrans.SettingsDialog import SettingsDialog
from GuiSubtrans.Widgets.OptionsWidgets import CheckboxOptionWidget, CreateOptionWidget, FloatOptionWidget, OptionWidget
from GuiSubtrans.Widgets.TranscriptionProviderLoader import TranscriptionProviderLoader
from PySubtrans.Helpers.Localization import _
from PySubtrans.Helpers.Time import TimedeltaToText
from PySubtrans.Options import Options
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleFormatRegistry import SubtitleFormatRegistry
from PySubtrans.SubtitleProject import SubtitleProject
from PySubtrans.Transcription.AudioExtractor import SUPPORTED_MEDIA_EXTENSIONS, CheckFfmpegAvailable
from PySubtrans.Transcription.TranscriptionCoordinator import TranscriptionCoordinator, TranscriptionStatus
from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionSegment




def _format_duration(seconds : float) -> str:
    """
    Format an elapsed-time estimate as m:ss.
    """
    total = max(0, int(seconds))
    return f"{total // 60}:{total % 60:02d}"


def _widget_row(*widgets : QWidget, stretch : bool = False) -> QHBoxLayout:
    """
    Pack widgets into a horizontal row, optionally with a trailing stretch.
    """
    row = QHBoxLayout()
    for widget in widgets:
        row.addWidget(widget)
    if stretch:
        row.addStretch(1)
    return row


class TranscriptionDialog(QDialog):
    """
    App-modal dialog for transcribing media to a translation-ready project.

    Builds a queue-owned transcription command and observes its signals
    while the main window stays blocked. Acceptance hands its project to
    the existing loading flow.
    """
    PROVIDER_ROW_START : int = 3

    commandRequested = Signal(object)

    def __init__(self, options : Options, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Transcribe Media"))
        self.setModal(True)
        self.setMinimumHeight(560)

        self.global_options : Options = options
        self.loader_thread : QThread|None = None
        self.project : SubtitleProject|None = None
        self.media_path : str|None = None
        self.provider : TranscriptionProvider|None = None
        self.provider_fields : dict[str, OptionWidget] = {}
        self._provider_row_count : int = 0
        self.fields : dict[str, OptionWidget] = {}
        self._phase : str = "setup"
        self._run_started : float = 0.0
        self._chunks_done : int = 0
        self._chunks_total : int = 0
        self._last_span : str = ""
        self._close_requested : bool = False
        self.active_command : TranscribeMediaCommand|None = None
        self._pending_accept : bool = False

        self._build_form()
        self.status_label.setText(_("Loading transcription providers..."))
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

        self.form = QFormLayout()
        self.form.setVerticalSpacing(4)
        left_layout.addLayout(self.form)

        self.file_edit = QLineEdit(self)
        self.file_edit.setPlaceholderText(_("Select a video or audio file..."))
        self.file_edit.textChanged.connect(self._on_file_changed)
        browse_button = self._button(_("Browse..."), self._browse_file)
        self.form.addRow(_("Media file"), _widget_row(self.file_edit, browse_button))

        self.track_combo = QComboBox(self)
        self.form.addRow(_("Audio track"), self.track_combo)

        self.provider_combo = QComboBox(self)
        self.provider_combo.currentTextChanged.connect(self._on_provider_changed)
        self.settings_button = self._button(_("Configure..."), self._open_transcription_settings)
        self.settings_button.setToolTip(_("Open transcription settings for this provider"))
        self.settings_button.setVisible(False)
        self.form.addRow(_("Provider"), _widget_row(self.provider_combo, self.settings_button))

        chunk_tooltip = _("Provider-recommended default; reselecting the provider restores it")
        seconds_suffix = _(" s")
        for key, default, limits, label in (
                ('min_chunk_seconds', 8.0, (1.0, 600.0), _("Min chunk length")),
                ('max_chunk_seconds', 60.0, (10.0, 1800.0), _("Max chunk length"))):
            field = cast(FloatOptionWidget, self._add_option_field(key, default, float, tooltip=chunk_tooltip))
            field.SetRange(*limits)
            field.SetSuffix(seconds_suffix)
            self.form.addRow(label, field)

        save_field = cast(CheckboxOptionWidget, self._add_option_field(
            'save_transcription', True, bool,
            tooltip=_("Write the transcription to a subtitle file alongside the media before translating")))
        format_field = self._add_option_field(
            'output_format', '.vtt', SubtitleFormatRegistry.enumerate_formats(),
            tooltip=_("VTT and ASS preserve speaker labels; SRT has no speaker field"))
        save_field.contentChanged.connect(lambda: format_field.setEnabled(save_field.GetValue()))
        self.form.addRow(_("Save transcribed subtitles"), _widget_row(save_field, format_field, stretch=True))

        clean_field = self._add_option_field(
            'postprocess_transcription', self.global_options.get_bool('postprocess_transcription', True), bool,
            tooltip=_("Apply the same post-processing used for translations (dashes, filler words, line breaks, etc.)"))
        self.form.addRow(clean_field.name, clean_field)
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

        self.transcribe_button = self._button(_("Transcribe"), self._start_transcription)
        self.abort_button = self._button(_("Abort"), self._abort_transcription)
        self.back_button = self._button(_("Back to Settings"), self._show_setup)
        layout.addLayout(_widget_row(self.transcribe_button, self.abort_button, self.back_button))

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Open | QDialogButtonBox.StandardButton.Close, self)
        self.button_box.button(QDialogButtonBox.StandardButton.Open).setText(_("Open as Project"))
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def _add_option_field(self, key : str, value : Any, key_type : Any, tooltip : str|None = None) -> OptionWidget:
        """
        Create an option widget, register it in self.fields and return it.
        """
        field = CreateOptionWidget(key, value, key_type, tooltip=tooltip)
        self.fields[key] = field
        return field

    def _button(self, text : str, handler : Callable[..., None]) -> QPushButton:
        """
        Create a push button wired to a click handler.
        """
        button = QPushButton(text, self)
        button.clicked.connect(handler)
        return button

    def _refresh_providers(self) -> None:
        """
        Load provider modules in a worker thread so the dialog appears
        immediately; the combo fills in when imports complete.
        """
        if self.loader_thread is not None:
            return
        self.provider_combo.clear()
        self.loader = TranscriptionProviderLoader()
        self.loader_thread = QThread(self)
        self.loader.moveToThread(self.loader_thread)
        self.loader_thread.started.connect(self.loader.run)
        self.loader.loaded.connect(self._on_providers_loaded)
        self.loader.failed.connect(self._on_providers_failed)
        self.loader.loaded.connect(self.loader_thread.quit)
        self.loader.failed.connect(self.loader_thread.quit)
        self.loader_thread.finished.connect(self.loader.deleteLater)
        self.loader_thread.finished.connect(self._on_loader_thread_finished)
        self.loader_thread.start()

    @Slot(list)
    def _on_providers_loaded(self, names : list) -> None:
        """Populate the provider combo once module imports complete."""
        self.provider_combo.addItems(names)
        if names:
            saved = self.global_options.get_str('transcription_provider')
            choice = saved if isinstance(saved, str) and saved in names else names[0]
            if self.provider_combo.currentText() != choice:
                self.provider_combo.setCurrentText(choice)
            else:
                self._on_provider_changed(choice)
        if self.media_path and os.path.isfile(self.media_path) and self.track_combo.count() == 0:
            self._load_tracks()
        elif not self.media_path:
            self.status_label.setText(_("Select a media file to begin."))

    @Slot(str)
    def _on_providers_failed(self, message : str) -> None:
        """Report provider loading failures instead of stalling silently."""
        logging.error(_("Unable to load transcription providers: {error}").format(error=message))
        self.status_label.setText(_("Unable to load transcription providers."))

    @Slot()
    def _on_loader_thread_finished(self) -> None:
        """Release the loader only after its QThread has actually stopped."""
        finished_thread = self.loader_thread
        self.loader_thread = None
        if finished_thread is not None:
            finished_thread.deleteLater()
        if self._close_requested and self.active_command is None:
            self._close_requested = False
            self.reject()

    def _current_provider(self) -> TranscriptionProvider|None:
        name = self.provider_name
        if not name:
            return None
        try:
            saved = TranscriptionCoordinator.ResolveProviderSettings(name, SettingsType(), self.global_options.get_dict('provider_settings'))
            return TranscriptionProvider.create_provider(name, saved)
        except Exception as e:
            logging.error(_("Unable to create transcription provider: {error}").format(error=str(e)))
            return None

    def _on_provider_changed(self, name : str) -> None:
        self.provider = self._current_provider()
        self._rebuild_provider_form()
        if self.provider is not None:
            # Chunk bounds follow the provider until the user overrides them
            self.fields['min_chunk_seconds'].SetValue(self.provider.recommended_min_chunk_seconds)
            self.fields['max_chunk_seconds'].SetValue(self.provider.recommended_max_chunk_seconds)
        self._update_settings_link()

    def _update_settings_link(self) -> None:
        """
        Show the Configure button when the selected provider is missing
        credentials, linking straight to its settings tab.
        """
        if self.provider is None:
            self.settings_button.setVisible(False)
            return
        for field in self.provider_fields.values():
            self.provider.settings[field.key] = field.GetValue()
        self.settings_button.setVisible(not self.provider.ValidateSettings())

    def _open_transcription_settings(self) -> None:
        """Edit transcription provider settings without leaving the dialog."""
        dialog = SettingsDialog(self.global_options, parent=self, focus_transcription_settings=True)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        updated = SettingsType({k: v for k, v in dialog.settings.items() if v != self.global_options.get(k)})
        if updated:
            self.global_options.update(updated)
            self.global_options.SaveSettings()
        self._on_provider_changed(self.provider_name)

    def _rebuild_provider_form(self) -> None:
        """
        Render the selected provider's per-run settings. Stable choices
        (models, keys, quotas) live in Settings; only basic options show here.
        """
        while self._provider_row_count > 0:
            self.form.removeRow(self.PROVIDER_ROW_START)
            self._provider_row_count -= 1

        self.provider_fields = {}
        if self.provider is None:
            return

        try:
            schema = self.provider.GetOptions(self.provider.settings)
        except Exception as e:
            logging.error(_("Unable to load provider options: {error}").format(error=str(e)))
            return

        for key, (key_type, tooltip) in schema.items():
            if key in self.provider.advanced_settings:
                continue
            field = CreateOptionWidget(key, self.provider.settings.get(key), key_type, tooltip=tooltip)
            field.contentChanged.connect(lambda dummy=None, k=field.key: self._on_provider_field_committed(k))
            self.provider_fields[key] = field
            self.form.insertRow(self.PROVIDER_ROW_START + self._provider_row_count, field.name, field)
            self._provider_row_count += 1

    def _on_provider_field_committed(self, key : str) -> None:
        """
        Refresh the per-run form when a refresh-triggering field commits
        (e.g. a key unlocking the progressive options), then update the
        Configure link as usual.
        """
        if self.provider is not None and key in self.provider.refresh_when_changed:
            self.provider.settings[key] = self.provider_fields[key].GetValue()
            self._rebuild_provider_form()
        self._update_settings_link()

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
            self._record_dependency_evidence(ffmpeg_available=True)
        except Exception as e:
            self._record_ffmpeg_if_missing(e)
            self.status_label.setText(_("Unable to read media: {error}").format(error=str(e)))

    def _record_dependency_evidence(self, ffmpeg_available : bool|None = None, torch_device : str|None = None) -> None:
        """
        Persist dependency facts learned from real runs, never from probes:
        ffmpeg proven by extraction or track listing; the torch device only
        when the run itself imported it (cloud providers pay nothing).
        """
        evidence : dict[str, object] = {}
        if ffmpeg_available is not None:
            evidence['transcription_ffmpeg_available'] = ffmpeg_available
        if torch_device:
            evidence['transcription_torch_device'] = torch_device
        changed = {key: value for key, value in evidence.items() if self.global_options.get(key) != value}
        if not changed:
            return
        try:
            self.global_options.update(changed)
            self.global_options.SaveSettings()
        except Exception as e:
            logging.debug(_("Unable to record dependency evidence: {error}").format(error=str(e)))

    def _record_ffmpeg_if_missing(self, error : Exception) -> None:
        """
        Clear the proven flag only when the failure is actually ffmpeg's
        absence (CheckFfmpegAvailable), not for unreadable media. Runs on
        the track-listing path, so no probing cost: classification reuses
        the failure that already happened.
        """
        try:
            CheckFfmpegAvailable()
        except Exception:
            self._record_dependency_evidence(ffmpeg_available=False)

    def _build_command(self) -> TranscribeMediaCommand|None:
        """Snapshot widget values for a queue-owned transcription run."""
        provider = self.provider
        if provider is None:
            self.status_label.setText(_("Transcription providers are still loading..."))
            return None
        for key, field in self.provider_fields.items():
            provider.settings[key] = field.GetValue()
        if not provider.ValidateSettings():
            self.status_label.setText(provider.validation_message or _("Invalid provider settings"))
            return None
        settings = SettingsType({
            'audio_track': self.track_combo.currentData() or 0,
            'language': provider.settings.get_str('language'),
            'min_chunk_seconds': self.fields['min_chunk_seconds'].GetValue(),
            'max_chunk_seconds': self.fields['max_chunk_seconds'].GetValue(),
            'transcription_align': True,
        })
        if self.media_path is None:
            return None
        output_format = str(self.fields['output_format'].GetValue() or '.srt').lstrip('.')
        return TranscribeMediaCommand(
            provider, self.media_path, settings, self._transcription_options(),
            save_transcription=self.fields['save_transcription'].GetValue(),
            output_format=output_format)

    def _transcription_options(self) -> Options:
        """
        Per-run project options: global defaults with this run's cleanup
        choice layered on top. The dialog never writes back to globals.
        """
        options = Options(self.global_options)
        options['postprocess_transcription'] = self.fields['postprocess_transcription'].GetValue()
        return options

    def _start_transcription(self) -> None:
        if self.active_command is not None:
            return
        if not self.media_path or not os.path.isfile(self.media_path):
            self.status_label.setText(_("Select a valid media file first."))
            return
        command = self._build_command()
        if command is None:
            return
        self.project = None
        self.results_view.clear()
        self._run_started = time.monotonic()
        self._chunks_done = 0
        self._chunks_total = 0
        self._last_span = ""
        self._pending_accept = False
        self._close_requested = False
        self.active_command = command
        command.progressed.connect(self._on_progress, Qt.ConnectionType.QueuedConnection)
        command.segmented.connect(self._on_segment, Qt.ConnectionType.QueuedConnection)
        self._show_results(True)
        self.status_label.setText(_("Transcribing..."))
        self.commandRequested.emit(command)
        # The completion observer is connected after submission so the queue's
        # own completion handling (undo bookkeeping and follow-up commands)
        # has been processed before the dialog reacts to the result.
        command.commandCompleted.connect(self._on_command_completed, Qt.ConnectionType.QueuedConnection)

    def _abort_transcription(self) -> None:
        """Stop the run after its current chunk; partial results are retained."""
        if self.active_command is not None:
            self.active_command.FinishEarly()
            self.status_label.setText(_("Aborting..."))

    @Slot(int, int, str)
    def _on_progress(self, done : int, total : int, span : str) -> None:
        self._chunks_done = done
        self._chunks_total = total
        self._last_span = span
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(done)
        else:
            # Total unknown while the chunk plan streams in: busy indicator
            self.progress_bar.setRange(0, 0)
        self._update_run_status()

    @Slot(object)
    def _on_segment(self, segment : TranscriptionSegment) -> None:
        """Append each transcribed line to the results pane as it completes."""
        start = TimedeltaToText(segment.start) or ""
        end = TimedeltaToText(segment.end) or ""
        span = f"{start} --> {end}"
        speaker = f"[{segment.speaker}] " if segment.speaker else ""
        self.results_view.append(f"[{span}] {speaker}{segment.text}")
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
        if self._chunks_total > 0:
            status = _("Transcribing chunk {current}/{total}").format(
                current=min(self._chunks_done + 1, self._chunks_total), total=self._chunks_total)
        else:
            status = _("Transcribing chunk {current}").format(current=self._chunks_done + 1)
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
    def _on_command_completed(self, command : TranscribeMediaCommand) -> None:
        """Consume the completion notification from the observed command."""
        if command is not self.active_command:
            return
        self.project = command.project
        if not command.aborted:
            # Extraction and inference provably ran: record what the run
            # learned about the local runtime for future sessions.
            self._record_dependency_evidence(
                ffmpeg_available=command.ffmpeg_available or None,
                torch_device=command.torch_device)
        count = self.project.subtitles.linecount if self.project and self.project.subtitles else 0
        if command.aborted or command.stopped_early:
            self.status_label.setText(_("Aborted - partial results ({} lines).").format(count))
        elif command.status is TranscriptionStatus.FAILED:
            self.status_label.setText(_("Transcription failed; partial results ({} lines) are available.").format(count)
                                      if count else _("Transcription failed: {error}").format(error=command.error))
        elif command.status is not TranscriptionStatus.COMPLETED:
            self.status_label.setText(_("Transcription incomplete - partial results ({} lines).").format(count))
        elif command.saved_path:
            message = _("Transcribed {} lines (saving to {}).").format(count, command.saved_path)
            self.status_label.setText(message)
            logging.info(message)
        else:
            message = _("Transcribed {} lines.").format(count)
            self.status_label.setText(message)
            logging.info(message)
        self.progress_bar.setRange(0, max(1, self.progress_bar.maximum()))
        self.progress_bar.setValue(self.progress_bar.maximum())
        command.progressed.disconnect(self._on_progress)
        command.segmented.disconnect(self._on_segment)
        command.commandCompleted.disconnect(self._on_command_completed)
        self.active_command = None
        self._show_results(False)
        if command.status is TranscriptionStatus.COMPLETED and not command.aborted:
            self._pending_accept = True
        if self._close_requested:
            self._close_requested = False
            self._pending_accept = False
            self.reject()
        elif self._pending_accept:
            self._pending_accept = False
            self.accept()

    def _has_unaccepted_results(self) -> bool:
        """Whether closing the dialog now would discard transcription results."""
        return (self.project is not None
                and self.project.subtitles is not None
                and self.project.subtitles.linecount > 0)

    def accept(self) -> None:
        """Keep the dialog alive until the queue command has stopped."""
        if self.active_command is not None:
            self._pending_accept = True
            return
        super().accept()

    def reject(self) -> None:
        """Confirm before discarding transcription results via Close or X."""
        if self.active_command is not None:
            if self._close_requested:
                # Second close attempt while aborting: force-close without
                # waiting for the in-flight request to finish or timeout.
                self.active_command = None
                self._close_requested = False
                super().reject()
                return
            self._close_requested = True
            self._pending_accept = False
            self._abort_transcription()
            return
        if self.loader_thread is not None and self.loader_thread.isRunning():
            self._close_requested = True
            return
        if self._has_unaccepted_results():
            count = self.project.subtitles.linecount if self.project and self.project.subtitles else 0
            reply = QMessageBox.question(
                self,
                _("Discard transcription?"),
                _("Discard the {} transcribed lines? They have not been opened as a project.").format(count),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return
        self._close_requested = False
        super().reject()

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
        self.back_button.setEnabled(self.active_command is None)
        open_button = self.button_box.button(QDialogButtonBox.StandardButton.Open)
        if open_button is not None:
            open_button.setEnabled(not running and self.active_command is None and self.project is not None)

    def closeEvent(self, event) -> None:
        """Keep the dialog alive until active background work has stopped."""
        event.ignore()
        self.reject()
