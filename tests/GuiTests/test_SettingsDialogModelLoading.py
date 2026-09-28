"""Exercise asynchronous provider model loading in the settings dialog."""
import logging
import time
from threading import Event
from unittest.mock import patch

from tests.GuiTestSupport import ConfigureOffscreenPlatform

ConfigureOffscreenPlatform()

from PySide6.QtWidgets import QApplication, QFormLayout, QLabel, QSizePolicy

from GuiSubtrans.SettingsDialog import SettingsDialog
from GuiSubtrans.Widgets.OptionsWidgets import InformationOptionWidget
from GuiSubtrans.Widgets.TranslationProviderModelLoader import TranslationProviderModelLoader
from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Helpers.Tests import skip_if_debugger_attached
from PySubtrans.Options import Options
from PySubtrans.SettingsType import GuiSettingsType, SettingsType
from PySubtrans.TranslationProvider import TranslationProvider
from tests.PySubtransTests.test_Transcription import FakeTranscriptionProvider


class FakeModelProvider(TranslationProvider):
    """Provider with a predictable model list, resolved on a worker thread."""
    name = "Fake Model Provider"
    default_model = "model-b"

    def __init__(self, settings : SettingsType):
        super().__init__(self.name, SettingsType({
            'api_key': settings.get_str('api_key', 'test-key'),
            'model': settings.get_str('model', self.default_model),
        }))
        self.refresh_when_changed = ['api_key', 'model']
        self.lookup_count = 0

    def GetAvailableModels(self) -> list[str]:
        self.lookup_count += 1
        return ['model-a', 'model-b', 'model-c']

    def GetOptions(self, settings : SettingsType) -> GuiSettingsType:
        """Build the schema from cached models, without triggering a lookup."""
        options : GuiSettingsType = {'api_key': (str, "API key")}
        models = self.model_list.known
        if models:
            options['model'] = (models, "Model")
        return options

    def GetInformation(self) -> str:
        return "Fake provider information"


class FailingModelProvider(FakeModelProvider):
    """Provider whose model lookup fails, to check the persisted model survives."""
    name = "Failing Model Provider"

    def GetAvailableModels(self) -> list[str]:
        raise RuntimeError("model service unavailable")


class EmptyModelProvider(FakeModelProvider):
    """Provider with no model list, to check an empty result is treated as authoritative."""
    name = "Empty Model Provider"

    def GetAvailableModels(self) -> list[str]:
        return []


class SlowModelProvider(FakeModelProvider):
    """Provider whose model lookup waits until released, to inspect the loading state."""
    name = "Slow Model Provider"

    def __init__(self, settings : SettingsType):
        super().__init__(settings)
        self._release = Event()

    def GetAvailableModels(self) -> list[str]:
        self._release.wait(2)
        return super().GetAvailableModels()

    def release(self) -> None:
        """Allow the pending lookup to complete."""
        self._release.set()


class GatedModelProvider(FakeModelProvider):
    """Provider whose lookup blocks until released, so a request can be superseded mid-flight."""
    name = 'Gated Model Provider'

    def __init__(self, settings : SettingsType):
        super().__init__(settings)
        self.credentials = 'old'
        self.lookup_started = Event()
        self._release = Event()

    def GetAvailableModels(self) -> list[str]:
        self.lookup_started.set()
        self._release.wait(5)
        return ['model-from-' + self.credentials]

    def release(self) -> None:
        """Let the pending lookup finish."""
        self._release.set()


class TestSettingsDialogModelLoading(LoggedTestCase):
    application : QApplication

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        existing = QApplication.instance()
        cls.application = existing if isinstance(existing, QApplication) else QApplication([])

    def _open_dialog(self, provider : TranslationProvider, model : str) -> SettingsDialog:
        options = Options({
            'provider': provider.name,
            'provider_settings': {provider.name: SettingsType({'model': model})},
        })
        options.add('available_providers', [provider.name])
        with patch.object(SettingsDialog, '_refresh_transcription_providers'):
            dialog = SettingsDialog(options, provider_cache={provider.name: provider})
        self.addCleanup(dialog.close)
        return dialog

    def _await_models(self, dialog : SettingsDialog) -> None:
        form = dialog.provider_form
        self.assertLoggedIsNotNone('provider form created', form)
        if form is None:
            return
        deadline = time.monotonic() + 2
        while form.provider.model_list.pending and time.monotonic() < deadline:
            self.application.processEvents()
            time.sleep(0.01)
        # Let the queued model-resolved rebuild run before inspecting the form
        for _dummy in range(5):
            self.application.processEvents()
            time.sleep(0.01)
        self.assertLoggedFalse('provider models resolved', form.provider.model_list.pending)

    def _model_field(self, dialog : SettingsDialog):
        form = dialog.provider_form
        return form.widgets.get('model') if form else None

    def _information_field(self, dialog : SettingsDialog, section : str):
        """Return the provider information field of a settings section, if present."""
        section_widget = dialog._sections.get(section)
        layout = section_widget.layout() if section_widget else None
        if not isinstance(layout, QFormLayout):
            return None

        for row in range(layout.rowCount()):
            item = layout.itemAt(row, QFormLayout.ItemRole.FieldRole)
            field = item.widget() if item is not None else None
            if getattr(field, 'key', None) == 'provider_info':
                return field

        return None

    def test_superseded_loader_cannot_overwrite_a_newer_result(self) -> None:
        """A loader superseded by a newer request cannot record its result."""
        provider = GatedModelProvider(SettingsType({'model': 'model-b'}))

        stale = TranslationProviderModelLoader(provider)
        stale.start()
        self.assertLoggedTrue('stale lookup started', provider.lookup_started.wait(2))
        self.assertLoggedTrue('list pending during lookup', provider.model_list.pending)

        # Supersede the in-flight request, then let the abandoned lookup finish
        stale.stop()
        provider.credentials = 'new'
        provider.release()

        deadline = time.monotonic() + 2
        while stale.running and time.monotonic() < deadline:
            self.application.processEvents()
            time.sleep(0.01)
        self.assertLoggedFalse('stale loader finished', stale.running)

        self.assertLoggedEqual('stale result discarded', [], provider.model_list.known)
        self.assertLoggedFalse('list left unresolved', provider.model_list.resolved)

        # The list stays retryable, and a fresh lookup sees the new credentials
        self.assertLoggedEqual('retry resolves with new credentials',
                               ['model-from-new'], provider.model_list.models)

    def test_provider_information_uses_the_shared_widget_in_both_tabs(self) -> None:
        """Provider information renders through the same widget in both settings tabs."""
        provider = FakeModelProvider(SettingsType({'model': 'model-b'}))
        dialog = self._open_dialog(provider, 'model-b')
        self._await_models(dialog)

        # The transcription tab is populated on demand, so supply a provider directly
        dialog.transcription_provider = FakeTranscriptionProvider()
        transcription_layout = dialog._sections[SettingsDialog.TRANSCRIPTION_SECTION].layout()
        dialog._populate_form(SettingsDialog.TRANSCRIPTION_SECTION, transcription_layout)

        translation_field = self._information_field(dialog, SettingsDialog.PROVIDER_SECTION)
        transcription_field = self._information_field(dialog, SettingsDialog.TRANSCRIPTION_SECTION)

        self.assertLoggedIsInstance('provider tab information field', translation_field, InformationOptionWidget)
        self.assertLoggedIsInstance('transcription tab information field', transcription_field, InformationOptionWidget)

        # Neither tab should hand the row to a space-filling text editor
        for description, field in (('provider tab', translation_field), ('transcription tab', transcription_field)):
            label = getattr(field, 'info_label', None)
            self.assertLoggedIsInstance(f'{description} information label', label, QLabel)
            if isinstance(label, QLabel):
                self.assertLoggedTrue(f'{description} information wraps', label.wordWrap())
                self.assertLoggedFalse(f'{description} information does not fill the form',
                                       label.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Expanding)

    def test_valid_model_is_preserved(self) -> None:
        """A persisted model that is still available stays selected."""
        provider = FakeModelProvider(SettingsType({'model': 'model-b'}))
        dialog = self._open_dialog(provider, 'model-b')

        self._await_models(dialog)

        self.assertLoggedEqual('model list loaded once', 1, provider.lookup_count)
        field = self._model_field(dialog)
        self.assertLoggedIsNotNone('model field created', field)
        if field is None:
            return
        self.assertLoggedEqual('valid model retained', 'model-b', field.GetValue())
        self.assertLoggedEqual('setting retained', 'model-b', dialog.provider_settings.get_dict(provider.name).get_str('model'))

    def test_invalid_model_is_corrected(self) -> None:
        """A persisted model that is no longer available is replaced with a valid one."""
        provider = FakeModelProvider(SettingsType({'model': 'retired-model'}))
        dialog = self._open_dialog(provider, 'retired-model')

        self._await_models(dialog)

        field = self._model_field(dialog)
        self.assertLoggedIsNotNone('model field created', field)
        if field is None:
            return
        self.assertLoggedEqual('invalid model replaced by first available', 'model-a', field.GetValue())
        self.assertLoggedEqual('setting corrected', 'model-a', dialog.provider_settings.get_dict(provider.name).get_str('model'))

    def test_persisted_model_shown_while_loading_then_preserved(self) -> None:
        """The persisted model is displayed during the load and kept once the list arrives."""
        provider = SlowModelProvider(SettingsType({'model': 'model-c'}))
        dialog = self._open_dialog(provider, 'model-c')

        form = dialog.provider_form
        self.assertLoggedIsNotNone('provider form created', form)
        if form is None:
            return

        try:
            self.assertLoggedTrue('load pending at first build', provider.model_list.pending)
            field = form.widgets.get('model')
            self.assertLoggedIsNotNone('model row present while loading', field)
            if field is not None:
                self.assertLoggedEqual('persisted model shown while loading', 'model-c', field.GetValue())
        finally:
            provider.release()

        self._await_models(dialog)
        field = self._model_field(dialog)
        self.assertLoggedIsNotNone('model field after load', field)
        if field is not None:
            self.assertLoggedEqual('persisted model preserved after load', 'model-c', field.GetValue())
            self.assertLoggedEqual('setting preserved after load', 'model-c', dialog.provider_settings.get_dict(provider.name).get_str('model'))

    def test_late_model_load_cannot_change_accepted_settings(self) -> None:
        """A model result queued after acceptance cannot mutate the accepted settings."""
        provider = FakeModelProvider(SettingsType({'model': 'retired-model'}))
        dialog = self._open_dialog(provider, 'retired-model')

        form = dialog.provider_form
        self.assertLoggedIsNotNone('provider form created', form)
        if form is None:
            return

        dialog.accept()

        request = provider.model_list.BeginLoad()
        provider.model_list.Resolve(request)
        form._on_models_loaded(provider.name)

        self.assertLoggedEqual(
            'accepted model remains unchanged after late load',
            'retired-model',
            dialog.provider_settings.get_dict(provider.name).get_str('model'))

    def test_provider_selector_switches_provider(self) -> None:
        """The provider selector remains available and switches the shown models."""
        provider_a = FakeModelProvider(SettingsType({'model': 'model-b'}))
        provider_a.name = "Fake Provider A"
        provider_b = FakeModelProvider(SettingsType({'model': 'model-b'}))
        provider_b.name = "Fake Provider B"

        options = Options({
            'provider': provider_a.name,
            'provider_settings': {provider_a.name: SettingsType({'model': 'model-b'})},
        })
        options.add('available_providers', [provider_a.name, provider_b.name])
        with patch.object(SettingsDialog, '_refresh_transcription_providers'):
            dialog = SettingsDialog(options, provider_cache={provider_a.name: provider_a, provider_b.name: provider_b})
        self.addCleanup(dialog.close)

        selector = dialog.widgets.get('provider')
        self.assertLoggedIsNotNone('provider selector present', selector)
        if selector is None:
            return
        self.assertLoggedEqual('selector lists all providers', [provider_a.name, provider_b.name], selector.values)
        self.assertLoggedEqual('selector shows current provider', provider_a.name, selector.GetValue())

    @skip_if_debugger_attached
    def test_failed_lookup_preserves_model(self) -> None:
        """A failed model lookup must not discard the persisted model."""
        provider = FailingModelProvider(SettingsType({'model': 'model-b'}))
        dialog = self._open_dialog(provider, 'model-b')

        with self.assertLogs(level=logging.WARNING):
            self._await_models(dialog)

        field = self._model_field(dialog)
        self.assertLoggedIsNotNone('model field created', field)
        if field is None:
            return
        self.assertLoggedEqual('persisted model preserved on failure', 'model-b', field.GetValue())
        self.assertLoggedEqual('setting preserved on failure', 'model-b', dialog.provider_settings.get_dict(provider.name).get_str('model'))

    def test_stable_rows_present_while_loading(self) -> None:
        """Provider rows that do not depend on the model list appear before it loads."""
        provider = SlowModelProvider(SettingsType({'model': 'model-b'}))
        dialog = self._open_dialog(provider, 'model-b')

        form = dialog.provider_form
        self.assertLoggedIsNotNone('provider form created', form)
        if form is None:
            return
        try:
            self.assertLoggedTrue('model load still pending', form.provider.model_list.pending)
            self.assertLoggedIn('api_key row present while loading', 'api_key', form.widgets)
        finally:
            provider.release()
            self._await_models(dialog)


class TestTranslationProviderModelLoader(LoggedTestCase):
    application : QApplication

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        existing = QApplication.instance()
        cls.application = existing if isinstance(existing, QApplication) else QApplication([])

    def test_empty_lookup_is_resolved(self) -> None:
        """An empty lookup is authoritative, since providers raise on a failed lookup."""
        provider = EmptyModelProvider(SettingsType({'model': 'model-b'}))
        loader = TranslationProviderModelLoader(provider)

        loader.run()

        self.assertLoggedTrue('empty lookup marked resolved', provider.model_list.resolved)
        self.assertLoggedFalse('not left pending', provider.model_list.pending)

    def test_abandoned_load_clears_pending(self) -> None:
        """Abandoning a loader must clear the pending request so later callers can fetch again."""
        provider = FakeModelProvider(SettingsType({'model': 'model-b'}))
        provider.model_list.BeginLoad()
        self.assertLoggedTrue('load pending', provider.model_list.pending)

        loader = TranslationProviderModelLoader(provider)
        loader.stop()

        self.assertLoggedFalse('pending cleared on abandon', provider.model_list.pending)
        models = provider.available_models
        self.assertLoggedEqual('models fetched again after abandon', ['model-a', 'model-b', 'model-c'], models)
        self.assertLoggedEqual('lookup performed after abandon', 1, provider.lookup_count)


if __name__ == '__main__':
    import unittest
    unittest.main()
