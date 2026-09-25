import logging
from collections.abc import Callable
from PySide6.QtCore import QThread, Slot
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QTabWidget, QDialogButtonBox, QWidget, QFormLayout, QFrame)
from GuiSubtrans.GuiHelpers import ClearForm, GetThemeNames

from GuiSubtrans.Widgets.OptionsWidgets import CreateOptionWidget, OptionWidget, ParseOptionDefinition
from GuiSubtrans.Widgets.ProviderSettingsForm import ProviderSettingsForm
from GuiSubtrans.Widgets.TranscriptionProviderLoader import TranscriptionProviderLoader
from PySubtrans.Helpers.InstructionsHelpers import GetInstructionsFiles, LoadInstructions
from PySubtrans.Options import ConfigActionOption, INFO_OPTION, Options
from GuiSubtrans.Widgets.TorchSetupDialog import TorchSetupDialog
from PySubtrans.SettingsType import SettingsType
from PySubtrans.Substitutions import Substitutions
from PySubtrans.Transcription.Torch.Runtime import TorchConfigOption
from PySubtrans.TranslationProvider import TranslationProvider
from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider
from PySubtrans.Helpers.Localization import LocaleDisplayItem, _, get_locale_display_items


class SettingsDialog(QDialog):
    """
    Dialog for editing user settings in various categories

    The settings are stored in a dictionary with a section for each tab and the settings it contains as key-value pairs.

    Each value is either a type indicating the type of the setting, or a tuple containing the type, tooltip, and optional placeholder text.

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
            'provider_info': (INFO_OPTION, _("Information about the selected transcription provider")),
            'transcription_provider_settings': TranscriptionProvider,
            'postprocess_transcription': (bool, _("Clean transcribed lines with the same normalizations used for loaded subtitles (dashes, filler words, line breaks)")),
            'ffmpeg_path': (str, _(
                "Optional path to the ffmpeg executable. Leave blank to use ffmpeg and ffprobe from the system PATH"
            ), _("Leave blank to use ffmpeg and ffprobe from the system PATH")),
        },
        'Processing': {
            'preprocess_subtitles': (bool, _("Preprocess subtitles when they are loaded")),
            'postprocess_translation': (bool, _("Postprocess subtitles after translation")),
            'extend_short_subtitles': (bool, _("Extend short subtitles to a minimum reading duration when saving")),
            'prevent_overlapping_times': (bool, _("Prevent overlapping subtitle display times")),
            'save_preprocessed_subtitles': (bool, _("Save preprocessed subtitles to a separate file")),
            'max_line_duration': (float, _("Maximum duration of a single line of subtitles")),
            'min_line_duration': (float, _("Minimum duration of a single line of subtitles")),
            'words_per_minute': (int, _("Reading speed used to extend short subtitles, in words per minute (other scripts are scaled to match). 0 applies only the minimum line duration")),
            'min_gap': (float, _("Minimum gap between consecutive subtitles, in seconds, used when preprocess_subtitles, extend_short_subtitles, or prevent_overlapping_times is enabled")),
            'merge_line_duration': (float, _("Merge lines with a duration less than this with the previous line")),
            'max_gap_for_merge': (float, _("Maximum gap between lines for them to be considered part of the same utterance")),
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
            'prewarm_providers': (bool, _("Load previously used translation providers after startup to make switching providers faster")),
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
        'words_per_minute': _duration_setting,
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

        self.translation_provider : TranslationProvider|None = None
        self.transcription_provider : TranscriptionProvider|None = None
        self.transcription_provider_names : list[str] = []
        self.loader_thread : QThread|None = None
        self.provider_form : ProviderSettingsForm|None = None
        self.provider_cache = provider_cache or {}
        self.settings : SettingsType = options.GetSettings()
        self.widgets = {}

        # Instance copy so dynamic population never mutates the class schema
        self.SECTIONS = {name: dict(section) for name, section in self.__class__.SECTIONS.items()}

        # Query available themes
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

        # The provider tab builds its form and loads models off-thread
        self._populate_provider_tab()

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
        self._stop_provider_model_load()

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
                        # Provider option fields live in the ProviderSettingsForm and are written as they change
                        if key == 'provider':
                            self.settings[key] = field.GetValue()
                    elif section_name == self.TRANSCRIPTION_SECTION:
                        if key == 'transcription_provider':
                            # Skip if providers haven't loaded yet (dropdown empty)
                            if field.GetValue():
                                self.settings[key] = field.GetValue()
                        elif self._is_root_setting(section_name, key):
                            # Declared section settings belong to the root
                            # settings object rather than a provider namespace.
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

    def reject(self):
        self._stop_provider_model_load()
        super().reject()

    def _get_provider_settings(self, provider : str) -> dict[str, SettingsType]:
        """ Get the settings for a specific provider """
        if not provider:
            return {}

        return self._get_namespaced_provider_settings(provider)

    def _get_transcription_provider_settings(self, provider : str) -> dict[str, SettingsType]:
        """Get the "<provider> Transcription" settings namespace, creating it on demand."""
        namespace = TranscriptionProvider.SettingsKey(provider)
        return self._get_namespaced_provider_settings(namespace)

    def _is_root_setting(self, section_name : str, key : str) -> bool:
        """Return whether a field is declared as a root setting in its section."""
        section_options = self.SECTIONS.get(section_name, {})
        return key in section_options and key in self.settings

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

    def _populate_provider_tab(self, provider_form : ProviderSettingsForm|None = None) -> None:
        """
        Rebuild the provider tab with the provider selector and the current provider's options
        """
        layout = self._get_section_layout(self.PROVIDER_SECTION)
        ClearForm(layout)

        provider = self.translation_provider
        if not provider:
            logging.warning("Translation provider is not configured")
            return

        provider_key = 'provider'
        key_type, tooltip, placeholder = ParseOptionDefinition(self.SECTIONS[self.PROVIDER_SECTION][provider_key])
        selector = CreateOptionWidget(
            provider_key,
            self.settings.get(provider_key),
            key_type,
            tooltip=tooltip,
            placeholder=placeholder)
        selector.contentChanged.connect(lambda field=selector: self._on_setting_changed(self.PROVIDER_SECTION, field.key, field.GetValue()))
        layout.addRow(selector.name, selector)
        self.widgets[provider_key] = selector

        if provider_form is not None:
            # Reuse the form that loaded the models, just repopulate its rows
            self.provider_form = provider_form
            provider_form.populate()
            return

        # Stop and detach any previous form before replacing it
        if self.provider_form is not None:
            self.provider_form.Stop()
            self.provider_form.settingChanged.disconnect()
            self.provider_form.modelsResolved.disconnect()

        self.provider_form = ProviderSettingsForm(provider, self.provider_settings.get_dict(provider.name), layout)
        # Bind the provider name so a superseded form cannot write into another provider's settings
        self.provider_form.settingChanged.connect(lambda key, value, name=provider.name: self._on_provider_setting_changed(name, key, value))
        self.provider_form.modelsResolved.connect(self._on_provider_models_resolved)

    def _on_provider_models_resolved(self) -> None:
        """
        Rebuild the provider rows once the model list has arrived, reusing the form that loaded it
        """
        self._populate_provider_tab(self.provider_form)

    def _on_provider_setting_changed(self, provider_name : str, key : str, value) -> None:
        """
        Apply a provider setting change and refresh the form when it affects the options
        """
        provider = self.translation_provider
        if not provider or provider.name != provider_name:
            # Ignore changes from a form for a provider that is no longer selected
            return

        provider_settings = self.provider_settings.get_dict(provider.name)
        provider_settings[key] = value

        if key in provider.refresh_when_changed:
            # Selecting a different model does not change the model list
            reset_available_models = key != 'model'
            if reset_available_models:
                provider.ResetAvailableModels()
                self._populate_provider_tab()
            else:
                provider.UpdateSettings(SettingsType(provider_settings))

    def _populate_form(self, section_name : str, layout : QFormLayout):
        """
        Create the form fields for the options
        """
        ClearForm(layout)

        options = self.SECTIONS[section_name]

        for key, option_definition in options.items():
            key_type, tooltip, placeholder = ParseOptionDefinition(option_definition)
            if key_type == TranslationProvider:
                pass
            elif key == 'provider' and section_name == self.PROVIDER_SECTION:
                # The provider selector is built by _populate_provider_tab
                pass
            elif key_type == TranscriptionProvider:
                self._add_transcription_provider_options(section_name, layout)
            elif key == 'provider_info':
                # This is a read-only field, not a setting to save.
                self._add_provider_info(section_name, layout)
            elif key in self.settings:
                field = CreateOptionWidget(
                    key,
                    self.settings[key],
                    key_type,
                    tooltip=tooltip,
                    placeholder=placeholder)
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

    def _add_provider_info(self, section_name : str, layout : QFormLayout) -> None:
        """
        Add the read-only provider information row to the form
        """
        if section_name != self.TRANSCRIPTION_SECTION or not self.transcription_provider:
            return

        provider_info = self.transcription_provider.GetInformation(
            ffmpeg_available=self.ffmpeg_available, torch_device=self.torch_device,
            display_language=self.settings.get_str('ui_language'))

        if not provider_info:
            return

        field = CreateOptionWidget('provider_info', provider_info, INFO_OPTION)
        layout.addRow(_("Provider information"), field)

    def _get_section_layout(self, section_name : str) -> QFormLayout:
        """
        Return the form layout for a section
        """
        section_widget = self._sections.get(section_name)
        if not section_widget:
            raise ValueError(f"Section {section_name} is not available")

        layout = section_widget.layout()
        if not isinstance(layout, QFormLayout):
            raise ValueError(f"Section {section_name} layout is not a QFormLayout")

        return layout

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

        # Wire up the loader signals and tear the thread down once it reports back
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

        # Replace the placeholder dropdown definition with the loaded provider names
        schema = self.SECTIONS[self.TRANSCRIPTION_SECTION]['transcription_provider']
        _key_type, tooltip, placeholder = ParseOptionDefinition(schema)
        self.SECTIONS[self.TRANSCRIPTION_SECTION]['transcription_provider'] = (
            list(names),
            tooltip,
            placeholder)

        # Keep the saved provider if it is still available, otherwise fall back to the first
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

    @property
    def ffmpeg_available(self) -> bool|None:
        """Whether ffmpeg has been proven available by a previous run."""
        ffmpeg = self.settings.get('transcription_ffmpeg_available')
        return ffmpeg if isinstance(ffmpeg, bool|None) else None

    @property
    def torch_device(self) -> str:
        """Torch device resolved by the last local transcription run."""
        return self.settings.get_str('transcription_torch_device') or "Unknown"

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
            resolved = TranscriptionProvider.ResolveProviderSettings(
                name, SettingsType(saved), self.settings.get_dict('provider_settings'))

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

        try:
            schema = self.transcription_provider.GetOptions(self.transcription_provider.settings)
        except Exception as e:
            logging.error(_("Unable to load transcription provider options: {error}").format(error=str(e)))
            return

        provider_name = self.transcription_provider.name

        for key, option_definition in schema.items():
            key_type, tooltip, placeholder = ParseOptionDefinition(option_definition)

            # Resolve ConfigActionOption sentinels to a callable handler so
            # CreateOptionWidget produces a ButtonTextOptionWidget.
            if isinstance(key_type, type) and issubclass(key_type, ConfigActionOption):
                placeholder = key_type.label
                key_type = self._get_setting_action_handler(key_type)

            field = CreateOptionWidget(
                key,
                self.transcription_provider.settings.get(key),
                key_type,
                tooltip=tooltip,
                placeholder=placeholder)
            # Bind the provider name so a superseded form cannot write into another provider's settings
            field.contentChanged.connect(lambda setting=field, name=provider_name: self._on_transcription_provider_setting_changed(name, setting.key, setting.GetValue()))
            layout.addRow(field.name, field)
            self.widgets[key] = field

    def _get_setting_action_handler(self, key_type : type) -> Callable[[str], str|None]:
        """Return a callable handler for a ConfigActionOption sentinel type.

        The handler takes the current setting value and returns the new value
        (or None to cancel).
        """
        if issubclass(key_type, TorchConfigOption):
            def _torch_handler(current_path : str) -> str|None:
                dialog = TorchSetupDialog(current_path, parent=self)
                if dialog.exec() == QDialog.DialogCode.Accepted:
                    return dialog.chosen_path
                return None
            return _torch_handler

        return lambda current_value: None

    def _stop_provider_model_load(self) -> None:
        """Prevent late provider model results from mutating settings after the dialog closes."""
        if self.provider_form is not None:
            self.provider_form.Stop()

    def closeEvent(self, event) -> None:
        """Stop the background loaders if the dialog closes early."""
        if self.loader_thread is not None and self.loader_thread.isRunning():
            self.loader_thread.quit()
            self.loader_thread.wait(5000)

        self._stop_provider_model_load()

        super().closeEvent(event)

    def _on_setting_changed(self, section_name, key, value):
        """
        Update the settings when a field is changed
        """
        if key == 'provider':
            self.settings[key] = value
            self._initialise_translation_provider()
            self._populate_provider_tab()

        elif key == 'transcription_provider':
            self.settings[key] = value
            self._initialise_transcription_provider()
            self._refresh_transcription_provider_options()

        elif key == 'instruction_file':
            self.settings[key] = value
            self._update_instruction_file()

        elif section_name == self.TRANSCRIPTION_SECTION:
            if self._is_root_setting(section_name, key):
                self.settings[key] = value
                self._update_section_visibility()
                self._update_setting_visibility()
                return

            provider = self.settings.get_str('transcription_provider')
            if not provider:
                logging.error(_("Transcription provider is not set"))
                return

            self._on_transcription_provider_setting_changed(provider, key, value)

        else:
            self.settings[key] = value
            self._update_section_visibility()
            self._update_setting_visibility()

    def _on_transcription_provider_setting_changed(self, provider_name : str, key : str, value) -> None:
        """
        Apply a transcription provider setting change and refresh the form when it affects the options.
        """
        provider = self.transcription_provider
        if not provider or provider.name != provider_name:
            # Ignore changes from a form for a provider that is no longer selected
            return

        namespace = self._get_transcription_provider_settings(provider_name)
        namespace[key] = value

        if key in provider.refresh_when_changed:
            self._refresh_transcription_provider_options()

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
