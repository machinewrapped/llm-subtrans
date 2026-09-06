"""Schema checks for SettingsDialog (no widgets instantiated)."""
import unittest

from GuiSubtrans.SettingsDialog import SettingsDialog
from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider
from PySubtrans.TranslationProvider import TranslationProvider


class TestSettingsDialogSchema(LoggedTestCase):
    def test_transcription_section_registered(self):
        """Settings carry a Transcription tab beside Provider Settings."""
        sections = SettingsDialog.SECTIONS

        self.assertLoggedIn("transcription tab", SettingsDialog.TRANSCRIPTION_SECTION, sections)
        self.assertLoggedIn("provider dropdown", "transcription_provider",
                             sections[SettingsDialog.TRANSCRIPTION_SECTION])

    def test_transcription_section_mirrors_provider_schema(self):
        """The transcription tab is provider-driven like the translation one."""
        transcription = SettingsDialog.SECTIONS[SettingsDialog.TRANSCRIPTION_SECTION]
        translation = SettingsDialog.SECTIONS[SettingsDialog.PROVIDER_SECTION]

        self.assertLoggedEqual("settings marker", TranscriptionProvider,
                               transcription['transcription_provider_settings'])
        self.assertLoggedEqual("translation marker untouched", TranslationProvider,
                               translation['provider_settings'])


if __name__ == '__main__':
    unittest.main()
