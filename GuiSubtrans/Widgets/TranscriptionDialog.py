import html
import logging
import os
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QDragEnterEvent, QDropEvent
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
from GuiSubtrans.Widgets.OptionsWidgets import (
    CreateOptionWidget,
    FloatOptionWidget,
    OptionWidget,
    ParseOptionDefinition,
)
from GuiSubtrans.Widgets.TranscriptionProviderLoader import TranscriptionProviderLoader
from GuiSubtrans.Widgets.TranscriptionRunProgress import TranscriptionRunProgress
from PySubtrans.Helpers.Localization import _
from PySubtrans.Helpers.Time import TimedeltaToText
from PySubtrans.Options import Options
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.SubtitleFormatRegistry import SubtitleFormatRegistry
from PySubtrans.Subtitles import Subtitles
from PySubtrans.Transcription.AudioExtractor import AudioChunker, SUPPORTED_MEDIA_EXTENSIONS, CheckFfmpegAvailable
from PySubtrans.Transcription.TranscriptionCoordinator import TranscriptionCoordinator
from PySubtrans.Transcription.TranscriptionOutcome import TranscriptionStatus
from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionSegment


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

    RUN_OPTION_DEFINITIONS = {
        'min_chunk_seconds': (float, _("Provider-recommended default;")),
        'max_chunk_seconds': (float, _("Provider-recommended default;")),
        'save_transcription': (bool, _("Write the transcription to a subtitle file alongside the media before translating")),
        'postprocess_transcription': (bool, _("Apply the same post-processing used for translations (dashes, filler words, line breaks, etc.)")),
    }

    commandRequested = Signal(object)

    def __init__(self, options : Options, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Transcribe Media"))
        self.setModal(True)
        self.setMinimumHeight(560)

        self.global_options : Options = options
        self.loader_thread : QThread|None = None
        self.subtitles : Subtitles|None = None
        self.media_path : str|None = None
        self.provider : TranscriptionProvider|None = None
        self.provider_fields : dict[str, OptionWidget] = {}
        self._provider_row_count : int = 0
        self.fields : dict[str, OptionWidget] = {}
        self._option_definitions : dict[str, Any] = {}
        self._phase : str = "setup"
        self.run_progress : TranscriptionRunProgress = TranscriptionRunProgress()
        self._close_requested : bool = False
        self.active_command : TranscribeMediaCommand|None = None
        self._completion_slot : Callable[[TranscribeMediaCommand], None]|None = None
        self._pending_accept : bool = False

        self._build_form()
        self.setAcceptDrops(True)
        self.status_label.setText(_("Loading transcription providers..."))
        self._refresh_providers()
        self._show_setup()

    @property
    def provider_name(self) -> str:
        """Currently selected transcription provider."""
        return str(self.provider_combo.currentText() or "")

    @property
    def _can_resume(self) -> bool:
        """
        Whether results are available to resume from. A run that completes
        cleanly closes the dialog, so any results still on show are partial.
        """
        return self.subtitles is not None and self.subtitles.linecount > 0

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
        self.file_edit.setReadOnly(True)
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

        self._option_definitions = dict(self.RUN_OPTION_DEFINITIONS)
        self._option_definitions['output_format'] = (
            SubtitleFormatRegistry.enumerate_formats(),
            _("VTT and ASS preserve speaker labels; SRT has no speaker field"))

        chunk_fields = (
            ("min_chunk_seconds", 8.0, (1.0, 600.0), _("Min chunk length")),
            ("max_chunk_seconds", 60.0, (10.0, 1800.0), _("Max chunk length")),
        )
        for key, default, limits, label in chunk_fields:
            field = self._add_option_row(key, default, label)
            if isinstance(field, FloatOptionWidget):
                field.SetRange(*limits)
                field.SetSuffix(_(" s"))

        save_field = self._create_option_field('save_transcription', True)
        format_field = self._create_option_field('output_format', '.vtt')
        save_field.contentChanged.connect(lambda: format_field.setEnabled(save_field.GetValue()))
        self.form.addRow(_("Save transcribed subtitles"), _widget_row(save_field, format_field, stretch=True))

        self._add_option_row(
            'postprocess_transcription',
            self.global_options.get_bool('postprocess_transcription', True))

        left_layout.addStretch(1)

        self.results_view = QTextEdit(self.splitter)
        self.results_view.setReadOnly(True)
        self.results_view.setPlaceholderText(_("Transcribed lines will appear here..."))

        self.splitter.addWidget(self.left_pane)
        self.splitter.addWidget(self.results_view)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([380, 520])

        self.warning_label = QLabel(self)
        self.warning_label.setWordWrap(True)
        self.warning_label.setTextFormat(Qt.TextFormat.RichText)
        self.warning_label.setVisible(False)
        layout.addWidget(self.warning_label)

        self.status_label = QLabel(_("Select a media file to begin."), self)
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.transcribe_button = self._button(_("Transcribe"), self._start_transcription)
        self.resume_button = self._button(_("Resume"), self._resume_transcription)
        self.abort_button = self._button(_("Abort"), self._abort_transcription)
        self.back_button = self._button(_("Back to Settings"), self._show_setup)

        # Resume is last so it always sits rightmost, whichever phase shows it
        layout.addLayout(_widget_row(self.transcribe_button, self.abort_button, self.back_button, self.resume_button))

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Open | QDialogButtonBox.StandardButton.Close, self)
        self.button_box.button(QDialogButtonBox.StandardButton.Open).setText(_("Open as Project"))
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def _create_option_field(
            self,
            key : str,
            value : Any,
            option_definition : Any|None = None,
            fields : dict[str, OptionWidget]|None = None) -> OptionWidget:
        """
        Create an option widget from schema metadata and register it.

        Omitted metadata and registry arguments refer to this dialog's
        transient run options. Dynamic provider fields provide both values.
        """
        if option_definition is None:
            option_definition = self._option_definitions[key]

        if fields is None:
            fields = self.fields

        key_type, tooltip, placeholder = ParseOptionDefinition(option_definition)
        field = CreateOptionWidget(
            key,
            value,
            key_type,
            tooltip=tooltip,
            placeholder=placeholder)

        fields[key] = field
        return field

    def _add_option_row(
            self,
            key : str,
            value : Any,
            label : str|None = None) -> OptionWidget:
        """Create, register, and add a schema-defined option row."""
        field = self._create_option_field(key, value)
        self.form.addRow(label or field.name, field)
        return field

    def _button(self, text : str, handler : Callable[..., None]) -> QPushButton:
        """
        Create a push button wired to a click handler.
        """
        button = QPushButton(text, self)
        button.clicked.connect(handler)
        return button

    def _set_open_enabled(self, enabled : bool) -> None:
        open_button = self.button_box.button(QDialogButtonBox.StandardButton.Open)
        if open_button is not None:
            open_button.setEnabled(enabled)

    # ---- Providers -------------------------------------------------------

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
            saved = TranscriptionProvider.ResolveProviderSettings(name, SettingsType(), self.global_options.get_dict('provider_settings'))
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
        self._update_language_warning()

    def _update_settings_link(self) -> None:
        """
        Show the Configure button when the selected provider is missing
        credentials, linking straight to its settings tab.
        """
        if self.provider is None:
            self.settings_button.setVisible(False)
            return

        self._apply_provider_fields(self.provider)
        self.settings_button.setVisible(not self.provider.ValidateSettings())

    def _update_language_warning(self) -> None:
        """
        Warn as soon as the language hint is committed if the provider
        cannot use it, rather than waiting for the run to be started.
        """
        warning = self.provider.LanguageWarning(self.global_options.ui_language) if self.provider else None

        self.warning_label.setText(f"<b>{_('Warning')}:</b> {html.escape(warning)}" if warning else "")
        self.warning_label.setVisible(bool(warning))

    def _apply_provider_fields(self, provider : TranscriptionProvider) -> None:
        """Copy the per-run provider field values onto the provider settings."""
        for key, field in self.provider_fields.items():
            provider.settings[key] = field.GetValue()

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

        for key, option_definition in schema.items():
            if key in self.provider.advanced_settings:
                continue

            field = self._create_option_field(
                key,
                self.provider.settings.get(key),
                option_definition=option_definition,
                fields=self.provider_fields)
            field.contentChanged.connect(lambda dummy=None, k=field.key: self._on_provider_field_committed(k))

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
        self._update_language_warning()

    # ---- Media -----------------------------------------------------------

    def _on_file_changed(self, path : str) -> None:
        self.media_path = path.strip() or None
        self.track_combo.clear()
        self.subtitles = None

        if self.media_path and os.path.isfile(self.media_path):
            self._load_tracks()

        if self._phase == "setup":
            self.transcribe_button.setEnabled(bool(self.media_path))

        self.progress_bar.setValue(0)
        self.results_view.clear()

    def _ffmpeg_settings(self) -> SettingsType:
        """Return the global ffmpeg setting for coordinator operations."""
        return SettingsType({'ffmpeg_path': self.global_options.get_str('ffmpeg_path')})

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
            coordinator = TranscriptionCoordinator(self.provider, self._ffmpeg_settings())
            tracks = coordinator.CheckRequirements(self.media_path)

            for track in tracks:
                self.track_combo.addItem(str(track), track.index)

            self.status_label.setText(_("Found {} audio track(s).").format(len(tracks)))
            self._record_dependency_evidence(ffmpeg_available=True)

        except Exception as e:
            self._record_ffmpeg_if_missing(e)
            self.status_label.setText(_("Unable to read media: {error}").format(error=str(e)))

    def _have_valid_media(self) -> bool:
        """Whether a readable media file is selected, reporting otherwise."""
        if self.media_path and os.path.isfile(self.media_path):
            return True

        self.status_label.setText(_("Select a valid media file first."))
        return False

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
            CheckFfmpegAvailable(self._ffmpeg_settings())
        except Exception:
            self._record_dependency_evidence(ffmpeg_available=False)

    # ---- Running a transcription ----------------------------------------

    def _build_command(self) -> TranscribeMediaCommand|None:
        """Snapshot widget values for a queue-owned transcription run."""
        provider = self.provider
        if provider is None:
            self.status_label.setText(_("Transcription providers are still loading..."))
            return None

        if self.media_path is None:
            return None

        self._apply_provider_fields(provider)
        if not provider.ValidateSettings():
            self.status_label.setText(provider.validation_message or _("Invalid provider settings"))
            return None

        min_chunk_seconds = self.fields['min_chunk_seconds'].GetValue()
        max_chunk_seconds = self.fields['max_chunk_seconds'].GetValue()

        try:
            AudioChunker.ValidateChunkBounds(min_chunk_seconds, max_chunk_seconds)
            language = provider.ResolveLanguageCode(provider.settings.get_str('language'), self.global_options.ui_language)

        except SubtitleError as e:
            self.status_label.setText(str(e))
            return None

        settings = SettingsType({
            'audio_track': self.track_combo.currentData() or 0,
            'language': language,
            'min_chunk_seconds': min_chunk_seconds,
            'max_chunk_seconds': max_chunk_seconds,
            'transcription_align': True,
            'ffmpeg_path': self.global_options.get_str('ffmpeg_path'),
            'max_characters': self.global_options.get_int('max_characters'),
            'max_line_duration': self.global_options.get_float('max_line_duration'),
            'min_split_chars': self.global_options.get_int('min_split_chars'),
        })

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
        if self.active_command is not None or not self._have_valid_media():
            return

        command = self._build_command()
        if command is None:
            return

        self.subtitles = None
        self.results_view.clear()
        self.run_progress.Reset()

        self._launch(command, _("Transcribing..."))

    def _resume_transcription(self) -> None:
        """Resume a previously aborted transcription from the last completed chunk."""
        if self.active_command is not None:
            return

        resume = self.subtitles
        if resume is None or not resume.originals or resume.originals[-1].end is None:
            self.status_label.setText(_("No partial results to resume from."))
            return

        if not self._have_valid_media():
            return

        command = self._build_command()
        if command is None:
            return

        command.prior_subtitles = resume

        # Keep the existing results visible; only restart the run timer.
        self.run_progress.Restart()

        self._launch(command, _("Resuming transcription..."))

    def _launch(self, command : TranscribeMediaCommand, status : str) -> None:
        """Observe the command, switch to the running view and submit it to the queue."""
        self._pending_accept = False
        self._close_requested = False
        self.active_command = command

        command.progressed.connect(self._on_progress, Qt.ConnectionType.QueuedConnection)
        command.audioProgressed.connect(self._on_audio_progress, Qt.ConnectionType.QueuedConnection)
        command.segmented.connect(self._on_segment, Qt.ConnectionType.QueuedConnection)

        self._show_results(True)
        self.status_label.setText(status)

        # Connect before submission so even an immediate failure is observed.
        self._completion_slot = self._defer_command_completed
        command.commandCompleted.connect(self._completion_slot, Qt.ConnectionType.QueuedConnection)
        self.commandRequested.emit(command)

    def _release(self, command : TranscribeMediaCommand) -> None:
        """Stop observing a finished command."""
        command.progressed.disconnect(self._on_progress)
        command.audioProgressed.disconnect(self._on_audio_progress)
        command.segmented.disconnect(self._on_segment)

        if self._completion_slot is not None:
            command.commandCompleted.disconnect(self._completion_slot)
            self._completion_slot = None

        self.active_command = None

    def _abort_transcription(self) -> None:
        """Stop the run after its current chunk; partial results are retained."""
        if self.active_command is not None:
            self.active_command.FinishEarly()
            self.status_label.setText(_("Aborting..."))

    @Slot(int, int, str)
    def _on_progress(self, done : int, total : int, span : str) -> None:
        self.run_progress.OnProgress(done, total, span)

        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(done)
        else:
            # Total unknown while the chunk plan streams in: busy indicator
            self.progress_bar.setRange(0, 0)

        self._update_run_status()

    @Slot(float, float)
    def _on_audio_progress(self, processed : float, total : float) -> None:
        """Track source-audio progress for ETA when chunk count is unknown."""
        self.run_progress.OnAudioProgress(processed, total)
        self._update_run_status()

    @Slot(object)
    def _on_segment(self, segment : TranscriptionSegment) -> None:
        """Append each transcribed line to the results pane as it completes."""
        start = TimedeltaToText(segment.start) or ""
        end = TimedeltaToText(segment.end) or ""
        speaker = f"[{segment.speaker}] " if segment.speaker else ""
        self.results_view.append(f"[{start} --> {end}] {speaker}{segment.text}")

        scrollbar = self.results_view.verticalScrollBar()
        if scrollbar is not None:
            scrollbar.setValue(scrollbar.maximum())

        self._update_run_status()

    def _update_run_status(self) -> None:
        self.status_label.setText(self.run_progress.StatusText())

    @Slot(object)
    def _defer_command_completed(self, command : TranscribeMediaCommand) -> None:
        """Defer dialog handling until the command queue finishes its bookkeeping."""
        QTimer.singleShot(0, lambda command=command: self._on_command_completed(command))

    @Slot(object)
    def _on_command_completed(self, command : TranscribeMediaCommand) -> None:
        """Consume the completion notification from the observed command."""
        if command is not self.active_command:
            return

        self.subtitles = command.subtitles

        if not command.aborted:
            # Extraction and inference provably ran: record what the run
            # learned about the local runtime for future sessions.
            self._record_dependency_evidence(
                ffmpeg_available=command.ffmpeg_available or None,
                torch_device=command.torch_device)

        self.status_label.setText(self._completion_message(command))
        self.progress_bar.setRange(0, max(1, self.progress_bar.maximum()))
        self.progress_bar.setValue(self.progress_bar.maximum())

        self._release(command)
        self._show_results(False)

        completed = command.status is TranscriptionStatus.COMPLETED and not command.aborted
        if self._close_requested:
            self._close_requested = False
            self._pending_accept = False
            self.reject()
        elif completed or self._pending_accept:
            self._pending_accept = False
            self.accept()

    @staticmethod
    def _completion_message(command : TranscribeMediaCommand) -> str:
        """Status line for a finished run, logging the successful cases."""
        count = command.transcribed_lines

        if command.aborted or command.stopped_early:
            return _("Aborted - partial results ({} lines).").format(count)

        if command.status is TranscriptionStatus.FAILED:
            if count:
                return _("Transcription failed; partial results ({} lines) are available.").format(count)
            return _("Transcription failed: {error}").format(error=command.error)

        if command.status is not TranscriptionStatus.COMPLETED:
            return _("Transcription incomplete - partial results ({} lines).").format(count)

        if command.saved_path:
            message = _("Transcribed {} lines (saving to {}).").format(count, command.saved_path)
        else:
            message = _("Transcribed {} lines.").format(count)

        logging.info(message)
        return message

    # ---- Dialog lifecycle ------------------------------------------------

    def _has_unaccepted_results(self) -> bool:
        """Whether closing the dialog now would discard transcription results."""
        return self._can_resume

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
            count = self.subtitles.linecount if self.subtitles else 0
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
        self.resume_button.setVisible(self._can_resume)
        self.resume_button.setEnabled(self._can_resume and bool(self.media_path))
        self.abort_button.setVisible(False)
        self.back_button.setVisible(False)

        self._set_open_enabled(self.subtitles is not None)

    def _show_results(self, running : bool) -> None:
        """
        Run/finish phase: full-width results, settings put away.
        """
        self._phase = "running" if running else "done"
        self.setMinimumWidth(920)

        self.left_pane.setVisible(False)
        self.results_view.setVisible(True)
        self.progress_bar.setVisible(True)

        can_resume = not running and self._can_resume
        self.transcribe_button.setVisible(False)
        self.resume_button.setVisible(can_resume)
        self.resume_button.setEnabled(can_resume)
        self.abort_button.setVisible(running)
        self.back_button.setVisible(not running)
        self.back_button.setEnabled(self.active_command is None)

        self._set_open_enabled(not running and self.active_command is None and self.subtitles is not None)

    def dragEnterEvent(self, event : QDragEnterEvent) -> None:
        """Accept drags that carry a single supported media file."""
        mime = event.mimeData()
        if mime and mime.hasUrls():
            urls = mime.urls()
            if len(urls) == 1 and urls[0].isLocalFile():
                path = urls[0].toLocalFile()
                if os.path.splitext(path)[1].casefold() in SUPPORTED_MEDIA_EXTENSIONS:
                    event.acceptProposedAction()
                    return

        event.ignore()

    def dropEvent(self, event : QDropEvent) -> None:
        """Set the media file from a dropped file."""
        mime = event.mimeData()
        if mime and mime.hasUrls():
            urls = mime.urls()
            if len(urls) == 1 and urls[0].isLocalFile():
                self.file_edit.setText(urls[0].toLocalFile())
                event.acceptProposedAction()
                return

        event.ignore()

    def closeEvent(self, event) -> None:
        """Keep the dialog alive until active background work has stopped."""
        event.ignore()
        self.reject()
