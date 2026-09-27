import logging

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtWidgets import QFormLayout

from GuiSubtrans.Widgets.OptionsWidgets import CreateOptionWidget, OptionWidget, ParseOptionDefinition
from GuiSubtrans.Widgets.TranslationProviderModelLoader import TranslationProviderModelLoader
from PySubtrans.Helpers.Localization import _
from PySubtrans.Options import INFO_OPTION
from PySubtrans.SettingsType import SettingsType
from PySubtrans.TranslationProvider import TranslationProvider


class ProviderSettingsForm(QObject):
    """
    Populates the provider-specific rows of a settings form.

    Injects rows directly into the host form layout so they align with the rest of the tab.
    Loads the model list off the GUI thread and reconciles the selected model when it arrives.
    """
    settingChanged = Signal(str, object)
    modelsResolved = Signal()

    def __init__(self, provider : TranslationProvider, settings : SettingsType, layout : QFormLayout):
        super().__init__(layout.parentWidget())
        self.provider = provider
        self.settings = settings
        self.layout = layout
        self.widgets : dict[str, OptionWidget] = {}
        self._loaders : list[TranslationProviderModelLoader] = []
        self._active : bool = True

        # Mark the load in progress before building so the persisted model is shown until it resolves
        if not self.provider.model_list.resolved:
            self.provider.model_list.BeginLoad()

        self.populate()
        self._start_model_load()

    def GetModel(self) -> str|None:
        """The currently displayed model, if the form has a model field."""
        field = self.widgets.get('model')
        value = field.GetValue() if field else None
        return value if isinstance(value, str) else None

    def Stop(self) -> None:
        """Stop any background model load."""
        self._active = False

        for loader in list(self._loaders):
            loader.stop()

    def populate(self) -> None:
        """Add the provider rows to the host layout."""
        self.widgets = {}
        provider_settings = self.provider.GetCombinedSettings(self.settings)
        schema = dict(self.provider.GetOptions(provider_settings))

        # The model row is shown while the list is not resolved, even when the schema omits it
        if 'model' not in schema and not self.provider.model_list.resolved:
            schema['model'] = ([], _( "AI model to use as the translator"))

        for key, option_definition in schema.items():
            field = self._create_field(key, option_definition, provider_settings)
            self.layout.addRow(field.name, field)
            self.widgets[key] = field

        self._add_provider_info()

    def _create_field(self, key : str, option_definition, provider_settings : SettingsType) -> OptionWidget:
        """Create a form field, showing the persisted model until the list is resolved."""
        key_type, tooltip, placeholder = ParseOptionDefinition(option_definition)
        initial_value = provider_settings.get(key)

        if key == 'model' and not self.provider.model_list.resolved:
            initial_value = self.settings.get_str('model') or self.provider.selected_model
            key_type = [initial_value] if initial_value else []

        field = CreateOptionWidget(key, initial_value, key_type, tooltip=tooltip, placeholder=placeholder)
        field.contentChanged.connect(lambda field=field: self.settingChanged.emit(field.key, field.GetValue()))
        return field

    def _add_provider_info(self) -> None:
        """Add the read-only provider information row."""
        provider_info = self.provider.GetInformation()
        if not provider_info:
            return

        # Top-align row labels so the label lines up with the multi-line information block
        self.layout.setLabelAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        field = CreateOptionWidget('provider_info', provider_info, INFO_OPTION)
        self.layout.addRow(_("Provider information"), field)

    def _start_model_load(self) -> None:
        """Load the model list off-thread when it has not been resolved."""
        if self.provider.model_list.resolved:
            self._reconcile_model()
            return

        # Apply the saved settings so the fetch uses the current API key and endpoints
        self.provider.UpdateSettings(SettingsType(self.settings))

        loader = TranslationProviderModelLoader(self.provider)
        loader.loaded.connect(self._on_models_loaded)
        loader.failed.connect(self._on_models_failed)
        loader.loaded.connect(lambda _name, loader=loader: self._release_loader(loader))
        loader.failed.connect(lambda _name, _message, loader=loader: self._release_loader(loader))

        self._loaders.append(loader)
        loader.start()

    def _release_loader(self, loader : TranslationProviderModelLoader) -> None:
        """Forget a loader once it has reported back."""
        if loader in self._loaders:
            self._loaders.remove(loader)

    @Slot(str)
    def _on_models_loaded(self, provider_name : str) -> None:
        """Reconcile the selection once the list arrives, preserving a model edited while loading."""
        if not self._active or provider_name != self.provider.name:
            return

        display_model = self.GetModel()
        if display_model:
            self.settings['model'] = display_model

        self._reconcile_model()
        self.modelsResolved.emit()

    @Slot(str, str)
    def _on_models_failed(self, provider_name : str, message : str) -> None:
        """Keep the persisted model when the model list cannot be loaded."""
        if not self._active or provider_name != self.provider.name:
            return

        logging.warning(_("Unable to load models for {provider}: {error}").format(provider=provider_name, error=message))
        self.modelsResolved.emit()

    def _reconcile_model(self) -> None:
        """Keep a valid selected model, replacing an unavailable one with a valid model."""
        if not self.provider.model_list.resolved or self.provider.model_list.pending:
            return

        available_models = self.provider.available_models
        selected_model = self.settings.get_str('model')

        if not available_models:
            logging.warning(_("No models available for {provider}").format(provider=self.provider.name))
        elif not selected_model or selected_model not in available_models:
            selected_model = available_models[0]
            self.settings['model'] = selected_model
            self.provider.UpdateSettings(SettingsType({'model': selected_model}))
            logging.info(_("Auto-selected model {model} for {provider} to ensure valid configuration").format(
                provider=self.provider.name,
                model=selected_model))
