"""Verify a transcription provider field writes to the settings of the provider its form was built for."""
import logging
from unittest.mock import patch

from tests.GuiTestSupport import ConfigureOffscreenPlatform

ConfigureOffscreenPlatform()

from PySide6.QtWidgets import QApplication

from GuiSubtrans.SettingsDialog import SettingsDialog
from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Options import Options
from PySubtrans.Subtitles import OriginalTextPlacement
from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider
from tests.PySubtransTests.test_Transcription import FakeTranscriptionProvider


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
