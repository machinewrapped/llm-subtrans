"""Verify a transcription provider field writes to the settings of the provider its form was built for."""
import logging
from unittest.mock import Mock, patch

from tests.GuiTestSupport import ConfigureOffscreenPlatform

ConfigureOffscreenPlatform()

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox

from GuiSubtrans.MainWindow import MainWindow
from GuiSubtrans.ProjectDataModel import ProjectDataModel
from GuiSubtrans.SettingsDialog import SettingsDialog
from GuiSubtrans.Widgets.ProjectSettings import ProjectSettings
from GuiSubtrans.Widgets.OptionsWidgets import DropdownOptionWidget
from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Options import Options
from PySubtrans.SettingsType import SettingsType
from PySubtrans.Subtitles import OriginalTextPlacement
from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider
from PySubtrans.TranslationProvider import ProviderKind
from tests.PySubtransTests.test_Transcription import FakeTranscriptionProvider
from tests.GuiTests.test_SettingsDialogModelLoading import FakeModelProvider


class TestTranscriptionProviderSettingBinding(LoggedTestCase):
    """A field must write to the settings of the provider its form was built for."""

    application : QApplication

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        existing = QApplication.instance()
        cls.application = existing if isinstance(existing, QApplication) else QApplication([])

    def _make_dialog(self) -> SettingsDialog:
        """Create a dialog without loading providers or model lists."""
        options = Options({'provider': 'OpenRouter'})

        with patch.object(SettingsDialog, '_refresh_transcription_providers'), \
                patch.object(SettingsDialog, '_initialise_translation_provider'):
            with self.assertLogs(level=logging.WARNING):
                return SettingsDialog(options)

    def test_setting_is_written_to_the_provider_namespace(self) -> None:
        """A transcription provider field writes to its own namespace."""
        dialog = self._make_dialog()
        try:
            provider = FakeTranscriptionProvider()
            dialog.transcription_provider = provider

            dialog._on_transcription_provider_setting_changed(provider.name, 'model', 'fake-model')

            namespace = dialog.settings.get_dict('provider_settings').get_dict(TranscriptionProvider.SettingsKey(provider.name))
            self.assertLoggedEqual('model recorded', 'fake-model', namespace.get('model'))
        finally:
            dialog.deleteLater()
            self.application.processEvents()

    def test_superseded_form_cannot_write_to_another_provider(self) -> None:
        """A change from a form for a provider that is no longer selected is ignored."""
        dialog = self._make_dialog()
        try:
            provider = FakeTranscriptionProvider()
            dialog.transcription_provider = provider

            dialog._on_transcription_provider_setting_changed('Some Other Provider', 'api_key', 'leaked-key')

            namespaces = dialog.settings.get_dict('provider_settings')
            for name, namespace in namespaces.items():
                if isinstance(namespace, dict):
                    self.assertLoggedNotIn('stale write ignored', 'leaked-key', list(namespace.values()), input_value=name)
        finally:
            dialog.deleteLater()
            self.application.processEvents()


class _GatewaySettingsProvider(FakeModelProvider):
    name = "Gateway Settings Test"
    kind = ProviderKind.Gateway


class _CloudSettingsProvider(FakeModelProvider):
    name = "Cloud Settings Test"
    kind = ProviderKind.Platform


class _DirectSettingsProvider(FakeModelProvider):
    name = "Direct Settings Test"
    kind = ProviderKind.Direct


class TestGatewaySettings(LoggedTestCase):
    """Gateway selections default to enabled and persist only when accepted."""

    application : QApplication

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        existing = QApplication.instance()
        cls.application = existing if isinstance(existing, QApplication) else QApplication([])

    def test_selector_updates_as_gateways_are_toggled(self) -> None:
        gateway = _GatewaySettingsProvider(SettingsType())
        direct = _DirectSettingsProvider(SettingsType())
        options = Options({'provider': gateway.name, 'available_providers': [direct.name, gateway.name]})
        with patch.object(SettingsDialog, '_refresh_transcription_providers'):
            dialog = SettingsDialog(options, provider_cache={gateway.name: gateway, direct.name: direct})
        try:
            selector = dialog.widgets.get('provider')
            self.assertLoggedIsInstance("provider selector", selector, DropdownOptionWidget)
            if not isinstance(selector, DropdownOptionWidget):
                return
            self.assertLoggedIn("gateway initially available", gateway.name, selector.values)
            dialog.gateway_checkboxes[gateway.name].setChecked(False)
            selector = dialog.widgets.get('provider')
            self.assertLoggedIsInstance("provider selector after fallback", selector, DropdownOptionWidget)
            if not isinstance(selector, DropdownOptionWidget):
                return
            self.assertLoggedNotIn("disabled gateway removed", gateway.name, selector.values)
            self.assertLoggedEqual("selection switches to enabled provider", direct.name, selector.GetValue())
            self.assertLoggedEqual("provider form switches with selection", direct.name, dialog.translation_provider.name if dialog.translation_provider else None)
            dialog.gateway_checkboxes[gateway.name].setChecked(True)
            self.assertLoggedIn("re-enabled gateway restored", gateway.name, selector.values)
            self.assertLoggedEqual("current selection preserved", direct.name, selector.GetValue())
            dialog.reject()
            self.assertLoggedEqual("cancel leaves options unchanged", [], options.get_str_list('disabled_gateways'))
        finally:
            dialog.close()
            dialog.deleteLater()
            self.application.processEvents()

    def test_cloud_provider_updates_selector_and_persists_in_dialog(self) -> None:
        cloud = _CloudSettingsProvider(SettingsType())
        direct = _DirectSettingsProvider(SettingsType())
        options = Options({'provider': direct.name, 'available_providers': [cloud.name, direct.name]})
        with patch.object(SettingsDialog, '_refresh_transcription_providers'):
            dialog = SettingsDialog(options, provider_cache={cloud.name: cloud, direct.name: direct})
        try:
            checkbox = dialog.cloud_provider_checkboxes[cloud.name]
            self.assertLoggedTrue("cloud enabled by default", checkbox.isChecked())
            checkbox.setChecked(False)
            selector = dialog.widgets.get('provider')
            self.assertLoggedIsInstance("provider selector", selector, DropdownOptionWidget)
            if isinstance(selector, DropdownOptionWidget):
                self.assertLoggedNotIn("cloud removed immediately", cloud.name, selector.values)
            dialog.accept()
            self.assertLoggedEqual("disabled cloud saved", [cloud.name], dialog.settings.get_str_list('disabled_cloud_providers'))
            self.assertLoggedEqual("original options unchanged", [], options.get_str_list('disabled_cloud_providers'))
        finally:
            dialog.deleteLater()
            self.application.processEvents()

    def test_open_project_selector_refreshes_after_settings_change(self) -> None:
        cloud = _CloudSettingsProvider.name
        gateway = _GatewaySettingsProvider.name
        direct = _DirectSettingsProvider.name
        model = ProjectDataModel(options=SettingsType({'provider': None}))
        panel = ProjectSettings()
        panel.datamodel = model
        panel.provider_list = [cloud, direct, gateway]
        panel.settings = SettingsType({'provider': direct})
        panel.BuildForm(panel.settings)
        try:
            model.project_options['disabled_cloud_providers'] = [cloud]
            model.project_options['disabled_gateways'] = [gateway]
            window = Mock(spec=MainWindow)
            window.toolbar = Mock()
            window.project_settings = panel
            MainWindow._settings_changed(window, {'disabled_cloud_providers': [cloud], 'disabled_gateways': [gateway]})
            self.assertLoggedNotIn("selector hidden with one available provider", 'provider', panel.widgets)
            model.project_options['disabled_gateways'] = []
            MainWindow._settings_changed(window, {'disabled_gateways': []})
            selector = panel.widgets.get('provider')
            self.assertLoggedIsInstance("selector rebuilt", selector, QComboBox)
            if isinstance(selector, QComboBox):
                self.assertLoggedEqual("disabled cloud absent", -1, selector.findText(cloud))
                self.assertLoggedGreater("gateway restored", selector.findText(gateway), -1)
        finally:
            panel.deleteLater()
            self.application.processEvents()

    def test_disabled_active_project_provider_survives_unrelated_edit(self) -> None:
        direct = _DirectSettingsProvider.name
        gateway = _GatewaySettingsProvider.name
        cloud = _CloudSettingsProvider.name
        for active, setting in ((gateway, 'disabled_gateways'), (cloud, 'disabled_cloud_providers')):
            with self.subTest(active=active):
                model = ProjectDataModel(options=SettingsType({'provider': None, setting: [active]}))
                panel = ProjectSettings()
                panel.datamodel = model
                panel.provider_list = [cloud, direct, gateway]
                panel.model_list = ['existing-model']
                panel.settings = SettingsType({'provider': active, 'model': 'existing-model'})
                panel.BuildForm(panel.settings)
                try:
                    selector = panel.widgets.get('provider')
                    self.assertLoggedIsInstance("provider selector", selector, QComboBox)
                    if not isinstance(selector, QComboBox):
                        continue
                    self.assertLoggedEqual("active provider displayed", active, selector.currentText())
                    self.assertLoggedFalse("disabled provider cannot be selected", bool(selector.model().flags(selector.model().index(selector.currentIndex(), 0)) & Qt.ItemFlag.ItemIsEnabled))
                    panel._text_changed()
                    settings = panel.GetSettings()
                    self.assertLoggedEqual("provider preserved after edit", active, settings.get_str('provider'))
                    self.assertLoggedEqual("model preserved after edit", 'existing-model', settings.get_str('model'))
                finally:
                    panel.deleteLater()
                    self.application.processEvents()

    def test_gateway_selection_and_fallback(self) -> None:
        gateway = _GatewaySettingsProvider(SettingsType())
        direct = _DirectSettingsProvider(SettingsType())
        names = [direct.name, gateway.name]
        options = Options({'provider': gateway.name, 'available_providers': names})
        with patch.object(SettingsDialog, '_refresh_transcription_providers'):
            dialog = SettingsDialog(options, provider_cache={gateway.name: gateway, direct.name: direct})
        try:
            self.assertLoggedEqual("gateways sorted", [gateway.name], list(dialog.gateway_checkboxes))
            self.assertLoggedTrue("gateway enabled by default", dialog.gateway_checkboxes[gateway.name].isChecked())
            dialog.gateway_checkboxes[gateway.name].setChecked(False)
            dialog.accept()
            self.assertLoggedEqual("disabled gateways saved", [gateway.name], dialog.settings.get_str_list('disabled_gateways'))
            self.assertLoggedEqual("selected provider remains available", direct.name, dialog.settings.get_str('provider'))
            self.assertLoggedEqual("original options unchanged", [], options.get_str_list('disabled_gateways'))
        finally:
            dialog.deleteLater()
            self.application.processEvents()


class TestEnumSettingSelection(LoggedTestCase):
    """An enum setting loaded from the settings file selects its member in the dropdown."""

    application : QApplication

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        existing = QApplication.instance()
        cls.application = existing if isinstance(existing, QApplication) else QApplication([])

    def test_saved_member_name_selects_member(self) -> None:
        """A placement saved by member name is selected rather than the first option."""
        options = Options({'provider': 'OpenRouter', 'original_text_placement': 'TranslationAboveOriginal'})

        with patch.object(SettingsDialog, '_refresh_transcription_providers'), \
                patch.object(SettingsDialog, '_initialise_translation_provider'):
            with self.assertLogs(level=logging.WARNING):
                dialog = SettingsDialog(options)

        try:
            field = dialog.widgets.get('original_text_placement')
            self.assertLoggedIsNotNone('placement field', field)
            if field is not None:
                self.assertLoggedEqual('selected placement', OriginalTextPlacement.TranslationAboveOriginal, field.GetValue())
        finally:
            dialog.deleteLater()
            self.application.processEvents()
