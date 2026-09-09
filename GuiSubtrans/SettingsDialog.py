import logging
from PySide6.QtCore import Qt, QThread, Slot
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QTabWidget, QDialogButtonBox, QWidget, QFormLayout, QFrame, QLabel, QScrollArea)
from GuiSubtrans.GuiHelpers import ClearForm, GetThemeNames

from GuiSubtrans.Widgets.OptionsWidgets import CreateOptionWidget, OptionWidget
from GuiSubtrans.Widgets.TranscriptionProviderLoader import TranscriptionProviderLoader
from PySubtrans.Helpers.InstructionsHelpers import GetInstructionsFiles, LoadInstructions
from PySubtrans.Options import Options
from PySubtrans.SettingsType import SettingsType
from PySubtrans.Substitutions import Substitutions
from PySubtrans.TranslationProvider import TranslationProvider
from PySubtrans.Transcription.TranscriptionCoordinator import TranscriptionCoordinator
from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider
from PySubtrans.Helpers.Localization import LocaleDisplayItem, _, get_locale_display_items


class SettingsDialog(QDialog):
    """
    Dialog for editing user settings in various categories

    The settings are stored in a dictionary with a section for each tab and the settings it contains as key-value pairs.

    Each value is either a type indicating the type of the setting, or a tuple containing the type and a tooltip string.

    The PROVIDER_SECTION is special and contains the settings for the translation provider, which are loaded dynamically based on the selected provider.

    The VISIBILITY_DEPENDENCIES dictionary contains the conditions for showing or hiding each section based on the settings.

    Some dropdowns are populated dynamically when the dialog is created, based on the available themes and instruction files.
    """
    PROVIDER_SECTION = 'Provider Settings'
    TRANSCRIPTION_SECTION = 'Transcription Settings'
    SECTIONS = {
        'General': {
            'ui_language': (str, _("The language of the application interface")),
            'theme': [],
            'target_language': (str, _("The default language to translate the subtitles to")),
            'build_terminology_map': (bool, _("Build a terminology map during translation to keep terminology consistent")),
            'include_original': (bool, _("Include original text in translated subtitles")),
            'add_right_to_left_markers': (bool, _("Add RTL markers around translated lines that contain primarily right-to-left script on save")),
            'instruction_file': (str, _("Instructions for the translation provider to follow")),
            'prompt': (str, _("The (brief) instruction for each batch of subtitles. Some [tags] are automatically filled in")),
            'project_file': (bool, _("Create a project file to allow resuming or revising translation")),
            'write_backup': (bool, _("Save a backup copy of the project when opening it")),
            'autosave': (bool, _("Automatically save the project/translation after each scene is translated")),
            'autosplit_on_error': (bool, _("If a batch fails validation, split it in half and retry each half separately")),
            'retry_on_error': (bool, _("If true, translations that fail validation will be retried with a note about the error")),
            'stop_on_error': (bool, _("Stop translating if an error is encountered"))
        },
        PROVIDER_SECTION: {
            'provider': ([], _("The AI translation service to use")),
            'provider_settings': TranslationProvider,
        },
        TRANSCRIPTION_SECTION: {
            'transcription_provider': ([], _("The transcription service to use")),
            'transcription_provider_settings': TranscriptionProvider,
            'postprocess_transcription': (bool, _("Clean transcribed lines with the same normalizations used for loaded subtitles (dashes, filler words, line breaks)")),
            'provider_info': (str, _("Information about the selected transcription provider")),
        },
        'Processing': {
            'preprocess_subtitles': (bool, _("Preprocess subtitles when they are loaded")),
            'postprocess_translation': (bool, _("Postprocess subtitles after translation")),
            'extend_short_subtitles': (bool, _("Extend short subtitles to a minimum reading duration when saving")),
            'prevent_overlapping_times': (bool, _("Prevent overlapping subtitle display times")),
            'save_preprocessed_subtitles': (bool, _("Save preprocessed subtitles to a separate file")),
            'max_line_duration': (float, _("Maximum duration of a single line of subtitles")),
            'min_line_duration': (float, _("Minimum duration of a single line of subtitles")),
            'seconds_per_character': (float, _("Minimum reading time per visible character in seconds")),
            'min_gap': (float, _("Minimum gap between consecutive subtitles, in seconds, used when preprocess_subtitles, extend_short_subtitles, or prevent_overlapping_times is enabled")),
            'merge_line_duration': (float, _("Merge lines with a duration less than this with the previous line")),
            'min_split_chars': (int, _("Minimum number of characters to split a line at")),
            'break_dialog_on_one_line': (bool, _("Add line breaks to text with dialog markers")),
            'normalise_dialog_tags': (bool, _("Ensure dialog markers match in multi-line subtitles")),
            'whitespaces_to_newline': (bool, _("Convert blocks of whitespace and Chinese Commas to newlines")),
            'full_width_punctuation': (bool, _("Ensure full-width punctuation is used in Asian languages")),
            'convert_wide_dashes': (bool, _("Convert wide dashes (emdash) to standard dashes")),
            'break_long_lines': (bool, _("Add line breaks to long single lines (post-process)")),
            'max_single_line_length': (int, _("Maximum length of a single line of subtitles")),
            'min_single_line_length': (int, _("Minimum length of a single line of subtitles")),
            'remove_filler_words': (bool, _("Remove filler_words and filler words from subtitles")),
            'filler_words': (str, _("Comma-separated list of filler_words to remove")),
        },
        'Advanced': {
            'max_threads': (int, _("Maximum number of simultaneous translation threads for fast translation")),
            'min_batch_size': (int, _("Avoid creating a new batch smaller than this")),
            'max_batch_size': (int, _("Divide any batches larger than this into multiple batches")),
            'scene_threshold': (float, _("Consider a new scene to have started after this many seconds without subtitles")),
            'substitution_mode': (Substitutions.Mode, _("Whether to substitute whole words or partial matches, or choose automatically based on input language")),
            'max_context_summaries': (int, _("Limits the number of scene/batch summaries to include as context with each translation batch")),
            'max_summary_length': (int, _("Maximum length of the context summary to include with each translation batch")),
            'max_characters': (int, _("Validator: Maximum number of characters to allow in a single translated line")),
            'max_newlines': (int, _("Validator: Maximum number of newlines to allow in a single translated line")),
            'max_retries': (int, _("Number of times to retry a failed translation before giving up")),
            'backoff_time': (float, _("Seconds to wait before retrying a failed translation")),
        }
    }

    _translated_sections = {
        'General': _("General"),
        PROVIDER_SECTION: _("Provider Settings"),
        TRANSCRIPTION_SECTION: _("Transcription Settings"),
        'Processing': _("Processing"),
        'Advanced': _("Advanced")
    }

    _preprocessor_setting = { 'preprocess_subtitles': True }
    _postprocessor_setting = { 'postprocess_translation': True }
    _duration_setting = { 'extend_short_subtitles': True }
    _overlap_setting = { 'prevent_overlapping_times': True }
    _prepostprocessor_setting = [ _preprocessor_setting, _postprocessor_setting ]

    VISIBILITY_DEPENDENCIES = {
        'write_backup': { 'project_file': True },
        # 'Processing' : [
        #     { 'preprocess_subtitles': True },
        #     { 'postprocess_translation': True }
        # ],
        'save_preprocessed_subtitles': _preprocessor_setting,
        'max_line_duration': _preprocessor_setting,
        'min_line_duration': [ _preprocessor_setting, _duration_setting ],
        'seconds_per_character': _duration_setting,
        'min_gap': [ _preprocessor_setting, _duration_setting, _overlap_setting ],
        'min_split_chars': _preprocessor_setting,
        'whitespaces_to_newline': _preprocessor_setting,
        'break_dialog_on_one_line': _prepostprocessor_setting,
        'normalise_dialog_tags': _prepostprocessor_setting,
        'full_width_punctuation': _prepostprocessor_setting,
        'convert_wide_dashes': _prepostprocessor_setting,
        'break_long_lines': _postprocessor_setting,
        'max_single_line_length': { 'postprocess_translation' : True, 'break_long_lines': True },
        'min_single_line_length': { 'postprocess_translation' : True, 'break_long_lines': True },
        'remove_filler_words': _prepostprocessor_setting,
        'filler_words': [
            { 'preprocess_subtitles': True, 'remove_filler_words': True },
            { 'postprocess_translation' : True, 'remove_filler_words': True }
        ]
    }

    def __init__(self, options : Options, provider_cache = None, parent=None, focus_provider_settings : bool = False,
                 focus_transcription_settings : bool = False):
        super().__init__(parent)
        self.setWindowTitle(_("GUI-Subtrans Settings"))
        self.setMinimumWidth(800)

        self.global_options : Options = options
        self.translation_provider : TranslationProvider|None = None
        self.transcription_provider : TranscriptionProvider|None = None
        self.transcription_provider_names : list[str] = []
        self.loader_thread : QThread|None = None
        self.provider_cache = provider_cache or {}
        self.settings : SettingsType = options.GetSettings()
        self.widgets = {}

        # Qyery available themes
        self.SECTIONS['General']['theme'] = ['default'] + GetThemeNames()

        # Available UI languages (dynamically detected) - hack to set the current locale as selected language
        self._locales = get_locale_display_items()
        self.SECTIONS['General']['ui_language'] = (self._locales, self.SECTIONS['General']['ui_language'][1])

        # Query available instruction files
        instruction_files = GetInstructionsFiles()
        if instruction_files:
            self.SECTIONS['General']['instruction_file'] = instruction_files

        # Populate available providers
        self.SECTIONS[self.PROVIDER_SECTION]['provider'] = (options.available_providers, self.SECTIONS[self.PROVIDER_SECTION]['provider'][1])

        try:
            # Initialise the current translation provider
            self._initialise_translation_provider()

        except Exception as e:
            logging.error(f"Unable to create translation provider '{self.settings.get('provider')}': {e}")
            self.settings['provider'] = "OpenRouter" if "OpenRouter" in options.available_providers else options.available_providers[0]
            self._initialise_translation_provider()

        # Initalise the tabs
        self._layout = QVBoxLayout(self)

        self._tabs = QTabWidget(self)
        self._layout.addWidget(self._tabs)
        self._sections = {}

        for section_name in self.SECTIONS.keys():
            section_widget = self._create_section_widget(section_name)
            tab_label = _(section_name)
            self._tabs.addTab(section_widget, tab_label)

        if focus_provider_settings:
            self._tabs.setCurrentWidget(self._sections[self.PROVIDER_SECTION])

        if focus_transcription_settings:
            self._tabs.setCurrentWidget(self._sections[self.TRANSCRIPTION_SECTION])

        # Transcription providers load off-thread; the tab fills in on arrival
        self._refresh_transcription_providers()

        # Conditionally hide or show tabs
        self._update_section_visibility()
        self._update_setting_visibility()

        # Add Ok and Cancel buttons
        self.buttonBox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        self._layout.addWidget(self.buttonBox)

    @property
    def provider_settings(self) -> SettingsType:
        return self.settings.get_dict('provider_settings')

    def accept(self):
        try:
            for section_name in self.SECTIONS.keys():
                section_widget = self._tabs.findChild(QWidget, section_name)
                if section_widget is None:
                    logging.warning(f"Unable to find section widget for {section_name}")
                    continue

                layout_qt = section_widget.layout()
                if not isinstance(layout_qt, QFormLayout):
                    raise ValueError(f"Section {section_name} layout is not a QFormLayout")
                layout : QFormLayout = layout_qt

                for row in range(layout.rowCount()):
                    item = layout.itemAt(row, QFormLayout.ItemRole.FieldRole)
                    field_qt = item.widget() if item is not None else None

                    if not isinstance(field_qt, OptionWidget):
                        continue

                    field : OptionWidget = field_qt

                    key = getattr(field, 'key')
                    if section_name == self.PROVIDER_SECTION:
                        if key == 'provider':
                            self.settings[key] = field.GetValue()
                        else:
                            provider = self.settings.get_str('provider') or 'Unknown'
                            provider_settings = self._get_provider_settings(provider)
                            provider_settings[key] = field.GetValue()
                    elif section_name == self.TRANSCRIPTION_SECTION:
                        if key == 'transcription_provider':
                            # Skip if providers haven't loaded yet (dropdown empty)
                            if field.GetValue():
                                self.settings[key] = field.GetValue()
                        elif key == 'postprocess_transcription':
                            # This is a global transcription default, rather
                            # than an option belonging to one provider.
                            self.settings[key] = field.GetValue()
                        elif key == 'provider_info':
                            # This is a read-only field, not a setting to save.
                            continue
                        else:
                            provider = self.settings.get_str('transcription_provider') or 'Unknown'
                            namespace = self._get_transcription_provider_settings(provider)
                            namespace[key] = field.GetValue()
                    elif key == 'ui_language':
                        if isinstance(field.GetValue(), LocaleDisplayItem):
                            self.settings[key] = field.GetValue().code
                    else:
                        self.settings[key] = field.GetValue()

        except Exception as e:
            logging.error(f"Unable to update settings: {e}")

        try:
            super().accept()

        except Exception as e:
            logging.error(f"Error in settings dialog handler: {e}")
            self.reject()

    def _get_provider_settings(self, provider : str) -> dict[str, SettingsType]:
        """ Get the settings for a specific provider """
        if not provider:
            return {}

        return self._get_namespaced_provider_settings(provider)

    def _get_transcription_provider_settings(self, provider : str) -> dict[str, SettingsType]:
        """Get the "<provider> Transcription" settings namespace, creating it on demand."""
        namespace = TranscriptionCoordinator.SettingsKey(provider)
        return self._get_namespaced_provider_settings(namespace)

    def _get_namespaced_provider_settings(self, namespace : str) -> dict[str, SettingsType]:
        """ Get the settings for a specific namespaced provider entry """
        if 'provider_settings' not in self.settings:
            self.settings['provider_settings'] = {}

        provider_settings = self.settings.get('provider_settings')

        if not isinstance(provider_settings, dict):
            raise Exception("provider_settings is not a valid dictionary")

        if namespace not in provider_settings:
            provider_settings[namespace] = {} # type: ignore[assignment]

        return provider_settings[namespace] # type: ignore[return-value]


    def _create_section_widget(self, section_name):
        """
        Create the form for a settings tab
        """
        section_widget = QFrame(self)
        section_widget.setObjectName(section_name)
        
        layout = QFormLayout(section_widget)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self._populate_form(section_name, layout)

        self._sections[section_name] = section_widget

        return section_widget

    def _populate_form(self, section_name : str, layout : QFormLayout):
        """
        Create the form fields for the options
        """
        ClearForm(layout)

        options = self.SECTIONS[section_name]

        for key, key_type in options.items():
            key_type, tooltip = key_type if isinstance(key_type, tuple) else (key_type, None)
            if key_type == TranslationProvider:
                self._add_provider_options(section_name, layout)
            elif key_type == TranscriptionProvider:
                self._add_transcription_provider_options(section_name, layout)
            elif key == 'provider_info':
                # This is a read-only field, not a setting to save.
                self._add_provider_info(section_name, layout)
            elif key in self.settings:
                field = CreateOptionWidget(key, self.settings[key], key_type, tooltip=tooltip)
                field.contentChanged.connect(lambda setting=field: self._on_setting_changed(section_name, setting.key, setting.GetValue()))
                layout.addRow(field.name, field)
                self.widgets[key] = field

    def _update_section_visibility(self):
        """
        Update the visibility of section tabs based on dependencies
        """
        for section_name, dependencies in self.VISIBILITY_DEPENDENCIES.items():
            section_tab = self._tabs.findChild(QWidget, section_name)
            if section_tab:
                if isinstance(dependencies, list):
                    visible = any(all(self.settings.get(key) == value for key, value in dependency.items()) for dependency in dependencies)
                else:
                    visible = all(self.settings.get(key) == value for key, value in dependencies.items())

                self._tabs.setTabVisible(self._tabs.indexOf(section_tab), visible)

    def _update_setting_visibility(self):
        """
        Update the visibility of individual settings based on dependencies
        """
        for key, field in self.widgets.items():
            if key in self.VISIBILITY_DEPENDENCIES:
                dependencies = self.VISIBILITY_DEPENDENCIES.get(key)
                if dependencies:
                    if isinstance(dependencies, list):
                        visible = any(all(self.settings.get(key) == value for key, value in dependency.items()) for dependency in dependencies)
                    else:
                        visible = all(self.settings.get(key) == value for key, value in dependencies.items())

                    self._update_setting_row_visibility(field, visible)

    def _update_setting_row_visibility(self, field, visible):
        """
        Update the visibility of a setting field
        """
        # Find the layout that contains the field
        # Find the parent row that contains the widget
        parent_widget : QWidget = field.parentWidget()
        layout_qt = parent_widget.layout()
        if not isinstance(layout_qt, QFormLayout):
            raise ValueError("Field is not in a QFormLayout")

        layout : QFormLayout = layout_qt
        if not layout:
            raise ValueError("Field is not in a layout")

        # Find the index of the row in the layout
        for row in range(layout.rowCount()):
            item = layout.itemAt(row, QFormLayout.ItemRole.FieldRole)
            if item is not None and item.widget() == field:
                layout.setRowVisible(row, visible)


    def _initialise_translation_provider(self):
        """
        Initialise translation provider
        """
        provider : str|None = self.settings.get_str('provider')
        if not provider:
            raise ValueError("Provider is not set")

        provider_settings = self.provider_settings.get_dict(provider)
        if provider not in self.provider_cache:
            self.provider_cache[provider] = TranslationProvider.create_provider(provider, provider_settings)

        self.translation_provider = self.provider_cache[provider]

        if self.translation_provider is not None:
            if provider not in self.provider_settings or not self.provider_settings[provider]:
                self.provider_settings[provider] = self.translation_provider.settings.copy()

    def _add_provider_options(self, section_name : str, layout : QFormLayout):
        """
        Add the options for a translation provider to a form
        """
        if not self.translation_provider:
            logging.warning("Translation provider is not configured")
            return

        saved_settings = self.provider_settings.get_dict(self.translation_provider.name)
        provider_settings = self.translation_provider.GetCombinedSettings(saved_settings)
        provider_options = self.translation_provider.GetOptions(provider_settings)

        for key, key_type in provider_options.items():
            key_type, tooltip = key_type if isinstance(key_type, tuple) else (key_type, None)
            field = CreateOptionWidget(key, provider_settings.get(key), key_type, tooltip=tooltip)
            field.contentChanged.connect(lambda setting=field: self._on_setting_changed(section_name, setting.key, setting.GetValue()))
            layout.addRow(field.name, field)
            self.widgets[key] = field

        self._add_provider_info(section_name, layout)

    def _add_provider_info(self, section_name : str, layout : QFormLayout):
        """
        Add a read-only field for provider information to the form
        """
        if section_name == self.TRANSCRIPTION_SECTION and self.transcription_provider:
            provider_info = self.transcription_provider.GetInformation(*self._transcription_dependency_state())
        elif section_name == self.PROVIDER_SECTION and self.translation_provider:
            provider_info = self.translation_provider.GetInformation()
        else:
            return

        if provider_info:
            self._add_provider_info_widget(layout, provider_info)

    def _add_provider_info_widget(self, layout, provider_info):
        """
        Create a rich text widget for provider information and add it to the layout
        """
        provider_container = QWidget()
        provider_layout = QVBoxLayout(provider_container)
        infoLabel = QLabel(provider_info)
        infoLabel.setWordWrap(True)
        infoLabel.setTextFormat(Qt.TextFormat.RichText)
        infoLabel.setOpenExternalLinks(True)
        provider_layout.addWidget(infoLabel)
        provider_layout.addStretch(1)

        scrollArea = QScrollArea()
        scrollArea.setWidgetResizable(True)
        scrollArea.setSizeAdjustPolicy(QScrollArea.SizeAdjustPolicy.AdjustToContents)
        scrollArea.setWidget(provider_container)
        layout.addRow(QLabel(_("Provider information")), scrollArea)

    def _refresh_provider_options(self):
        """
        Populate the provider-specific options
        """
        if not self.translation_provider:
            logging.warning("Translation provider is not configured")
            return

        self.translation_provider.ResetAvailableModels()

        provider_settings = self.provider_settings.get_dict(self.translation_provider.name)
        provider_settings = SettingsType(provider_settings)
        self.translation_provider.UpdateSettings(provider_settings)

        selected_model = provider_settings.get_str('model')
        if not self.translation_provider.available_models:
            logging.warning(_("No models available for {provider}").format(provider = self.translation_provider.name))
        elif not selected_model or selected_model not in self.translation_provider.available_models:
            # Auto-select an available model
            selected_model = self.translation_provider.available_models[0]
            provider_settings['model'] = selected_model
            self.translation_provider.UpdateSettings(provider_settings)
            self.provider_settings.get_dict(self.translation_provider.name)['model'] = self.translation_provider.selected_model
            logging.info(_("Auto-selected model {model} for {provider} to ensure valid configuration").format(
                provider=self.translation_provider.name,
                model=selected_model))

        section_name = self.PROVIDER_SECTION
        section_widget = self._sections.get(section_name)
        if section_widget:
            section_layout = section_widget.layout()
            self._populate_form(section_name, section_layout)

    def _refresh_transcription_providers(self) -> None:
        """
        Load transcription provider names off the GUI thread; the tab
        fills in when imports complete.
        """
        if self.loader_thread is not None:
            return
        self.loader = TranscriptionProviderLoader()
        self.loader_thread = QThread(self)
        self.loader.moveToThread(self.loader_thread)
        self.loader_thread.started.connect(self.loader.run)
        self.loader.loaded.connect(self._on_transcription_providers_loaded)
        self.loader.failed.connect(self._on_transcription_providers_failed)
        self.loader.loaded.connect(self.loader_thread.quit)
        self.loader.failed.connect(self.loader_thread.quit)
        self.loader_thread.finished.connect(self.loader.deleteLater)
        self.loader_thread.start()

    @Slot(list)
    def _on_transcription_providers_loaded(self, names : list) -> None:
        """Populate the transcription tab once module imports complete."""
        self.loader_thread = None
        self.transcription_provider_names = list(names)
        schema = self.SECTIONS[self.TRANSCRIPTION_SECTION]['transcription_provider']
        tooltip = schema[1] if isinstance(schema, tuple) else None
        self.SECTIONS[self.TRANSCRIPTION_SECTION]['transcription_provider'] = (list(names), tooltip)
        saved = self.settings.get_str('transcription_provider')
        self.settings['transcription_provider'] = saved if saved in names else (names[0] if names else None)
        self._initialise_transcription_provider()
        section_widget = self._sections.get(self.TRANSCRIPTION_SECTION)
        if section_widget:
            section_layout = section_widget.layout()
            self._populate_form(self.TRANSCRIPTION_SECTION, section_layout)
            combo = self.widgets.get('transcription_provider')
            if combo is not None and hasattr(combo, 'SetValue'):
                combo.SetValue(self.settings.get_str('transcription_provider'))

    @Slot(str)
    def _on_transcription_providers_failed(self, message : str) -> None:
        """Report provider loading failures instead of stalling silently."""
        self.loader_thread = None
        logging.error(_("Unable to load transcription providers: {error}").format(error=message))

    def _transcription_dependency_state(self) -> tuple[bool|None, str]:
        """
        Cached dependency evidence for provider info: ffmpeg proven (or not)
        and the resolved torch device from the last local run. Never probes
        here; writers live on the transcription run paths.
        """
        ffmpeg = self.settings.get('transcription_ffmpeg_available')
        ffmpeg_available = ffmpeg if isinstance(ffmpeg, bool|None) else None
        torch_device = self.settings.get_str('transcription_torch_device') or "Unknown"
        return ffmpeg_available, torch_device

    def _initialise_transcription_provider(self) -> None:
        """
        Initialise the transcription provider from saved settings, resolving
        shared credentials so inherited API keys display in the form.
        """
        name = self.settings.get_str('transcription_provider')
        if not name:
            return
        try:
            saved = self._get_transcription_provider_settings(name)
            resolved = TranscriptionCoordinator.ResolveProviderSettings(
                name, SettingsType(saved), self.global_options)
            self.transcription_provider = TranscriptionProvider.create_provider(name, resolved)
        except Exception as e:
            logging.error(f"Unable to create transcription provider '{name}': {e}")
            self.transcription_provider = None

    def _refresh_transcription_provider_options(self) -> None:
        """
        Rebuild the transcription tab after provider or key changes.
        """
        if not self.transcription_provider:
            return

        self.transcription_provider.ResetAvailableModels()
        self._initialise_transcription_provider()

        section_widget = self._sections.get(self.TRANSCRIPTION_SECTION)
        if section_widget:
            section_layout = section_widget.layout()
            self._populate_form(self.TRANSCRIPTION_SECTION, section_layout)

    def _add_transcription_provider_options(self, section_name : str, layout : QFormLayout) -> None:
        """
        Add the options for a transcription provider to a form.
        """
        if not self.transcription_provider:
            return

        # layout.addRow(QLabel(_("Provider options")))

        try:
            schema = self.transcription_provider.GetOptions(self.transcription_provider.settings)
        except Exception as e:
            logging.error(_("Unable to load transcription provider options: {error}").format(error=str(e)))
            return

        for key, key_type in schema.items():
            key_type, tooltip = key_type if isinstance(key_type, tuple) else (key_type, None)
            field = CreateOptionWidget(key, self.transcription_provider.settings.get(key), key_type, tooltip=tooltip)
            field.contentChanged.connect(lambda setting=field: self._on_setting_changed(section_name, setting.key, setting.GetValue()))
            layout.addRow(field.name, field)
            self.widgets[key] = field

    def closeEvent(self, event) -> None:
        """Stop the provider loader if the dialog closes early."""
        if self.loader_thread is not None and self.loader_thread.isRunning():
            self.loader_thread.quit()
            self.loader_thread.wait(5000)
        super().closeEvent(event)

    def _on_setting_changed(self, section_name, key, value):
        """
        Update the settings when a field is changed
        """
        if key == 'provider':
            self.settings[key] = value
            self._initialise_translation_provider()
            self._refresh_provider_options()

        elif key == 'transcription_provider':
            self.settings[key] = value
            self._initialise_transcription_provider()
            self._refresh_transcription_provider_options()

        elif key == 'instruction_file':
            self.settings[key] = value
            self._update_instruction_file()

        elif section_name == self.PROVIDER_SECTION:
            provider = self.settings.get_str('provider')
            if not provider:
                logging.error(_("Provider is not set"))
                return

            provider_settings = self._get_provider_settings(provider)
            provider_settings[key] = value

            if self.translation_provider and key in self.translation_provider.refresh_when_changed:
                self._refresh_provider_options()

        elif section_name == self.TRANSCRIPTION_SECTION:
            if key == 'postprocess_transcription':
                self.settings[key] = value
                self._update_section_visibility()
                self._update_setting_visibility()
                return

            provider = self.settings.get_str('transcription_provider')
            if not provider:
                logging.error(_("Transcription provider is not set"))
                return

            namespace = self._get_transcription_provider_settings(provider)
            namespace[key] = value

            if self.transcription_provider and key in self.transcription_provider.refresh_when_changed:
                self._refresh_transcription_provider_options()

        else:
            self.settings[key] = value
            self._update_section_visibility()
            self._update_setting_visibility()

    def _update_instruction_file(self):
        """
        Update the prompt when the instruction file is changed
        """
        instruction_file = self.widgets['instruction_file'].GetValue()
        if instruction_file:
            try:
                instructions = LoadInstructions(instruction_file)
                self.widgets['prompt'].SetValue(instructions.prompt)
                if instructions.target_language:
                    self.widgets['target_language'].SetValue(instructions.target_language)

            except Exception as e:
                logging.error(f"Unable to load instructions from {instruction_file}: {e}")

