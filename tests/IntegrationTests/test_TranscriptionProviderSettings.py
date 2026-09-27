"""Checks on the settings every concrete transcription provider declares.

A language hint is validated in the provider information, so changing it has to refresh the
form - declared on the provider rather than special-cased by key in the dialog.

Concrete providers cannot be imported by the unit suites (see tests/ProviderImportGuard.py),
so these checks live in the integration suite.
"""
import os
from unittest.mock import patch

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Options import Options
from PySubtrans.SettingsType import SettingsType
from PySubtrans.Transcription.Providers.Provider_OpenRouter import OpenRouterTranscriptionProvider
from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider


class TestTranscriptionProviderRefreshTriggers(LoggedTestCase):
    """Every provider offering a language hint declares it as a refresh trigger."""

    def test_language_is_declared_where_it_is_offered(self) -> None:
        for name, provider_class in sorted(TranscriptionProvider.get_providers().items()):
            provider = provider_class(SettingsType())

            if 'language' not in provider.settings:
                continue

            self.assertLoggedIn(f'{name} refreshes on language', 'language', provider.refresh_when_changed,
                                input_value=provider.refresh_when_changed)


class TestTranscriptionProviderUnsetSettings(LoggedTestCase):
    """A setting with no default is still a known key, so a later update applies to it."""

    def test_unset_rate_limit_can_be_updated(self) -> None:
        # Every provider's rate limit defaults to its environment variable, which is None when unset
        unset_environment = {key: value for key, value in os.environ.items() if not key.endswith('RATE_LIMIT')}

        with patch.dict(os.environ, unset_environment, clear=True):
            for name, provider_class in sorted(TranscriptionProvider.get_providers().items()):
                provider = provider_class(SettingsType())
                provider.UpdateSettings(SettingsType({'rate_limit': 12.0}))

                self.assertLoggedEqual(f'{name} rate limit', 12.0, provider.settings.get_float('rate_limit'))


class TestTranscriptionProviderChunkSettings(LoggedTestCase):
    """Chunk bounds are provider settings, each provider with its own defaults."""

    def test_every_provider_declares_chunk_bounds(self) -> None:
        for name, provider_class in sorted(TranscriptionProvider.get_providers().items()):
            provider = provider_class(SettingsType())
            min_chunk_seconds = provider.settings.get_float('min_chunk_seconds')
            max_chunk_seconds = provider.settings.get_float('max_chunk_seconds')

            self.assertLoggedIsNotNone(f'{name} min chunk default', min_chunk_seconds)
            self.assertLoggedIsNotNone(f'{name} max chunk default', max_chunk_seconds)
            self.assertLoggedLessEqual(f'{name} min within max', min_chunk_seconds, max_chunk_seconds)

    def test_saved_settings_override_defaults(self) -> None:
        """A saved chunk bound wins over the provider default; the other keeps its default."""
        options = Options()
        options.provider_settings[TranscriptionProvider.SettingsKey('OpenRouter')] = SettingsType({
            'api_key': 'k',
            'min_chunk_seconds': 45.0,
        })
        resolved = TranscriptionProvider.ResolveProviderSettings(
            'OpenRouter', SettingsType(), options.get_dict('provider_settings'))
        provider = OpenRouterTranscriptionProvider(resolved)
        default = OpenRouterTranscriptionProvider(SettingsType({'api_key': 'k'}))

        self.assertLoggedEqual('saved min', 45.0, provider.settings.get_float('min_chunk_seconds'))
        self.assertLoggedEqual('default max', default.settings.get_float('max_chunk_seconds'),
                               provider.settings.get_float('max_chunk_seconds'))
