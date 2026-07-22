from PySubtrans.Helpers.TestCases import DummyProvider, LoggedTestCase
from PySubtrans.Helpers.Tests import log_input_expected_error, skip_if_debugger_attached
from PySubtrans.Options import Options
from PySubtrans.SettingsType import SettingsType
from PySubtrans.TranslationProvider import TranslationProvider


class TranslationProviderTests(LoggedTestCase):

    def test_create_provider_case_insensitive(self):
        """create_provider accepts a non-canonical provider name casing"""
        provider = TranslationProvider.create_provider("dummy provider", SettingsType())
        self.assertLoggedIsInstance("case-insensitive lookup returns DummyProvider", provider, DummyProvider)

    @skip_if_debugger_attached
    def test_create_provider_unknown_raises(self):
        """create_provider raises ValueError for an unregistered provider name"""
        with self.assertRaises(ValueError) as context:
            TranslationProvider.create_provider("no such provider", SettingsType())
        log_input_expected_error("no such provider", ValueError, context.exception)

    def test_get_provider_normalizes_name(self):
        """get_provider normalizes options.provider to the canonical registered name and applies settings"""
        options = Options({
            'provider': 'dummy provider',
            'provider_settings': {
                'Dummy Provider': SettingsType({'model': 'test-model-xyz'})
            },
            'target_language': 'French',
        })

        provider = TranslationProvider.get_provider(options)

        self.assertLoggedIsInstance("get_provider returns DummyProvider", provider, DummyProvider)
        self.assertLoggedEqual("options.provider normalized to canonical name", "Dummy Provider", options.provider)
        self.assertLoggedEqual("provider received settings from options", "test-model-xyz", provider.settings.get_str('model'))
