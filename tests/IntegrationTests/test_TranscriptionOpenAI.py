import os
import unittest
from datetime import timedelta
from unittest.mock import Mock, patch

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider
from PySubtrans.Transcription.Providers.Provider_OpenAI import (
    OpenAITranscriptionProvider,
    parse_diarized_payload,
)


class TestOpenAIRegistered(LoggedTestCase):
    def test_registered(self):
        """OpenAI always registers (HTTP-only, no SDK)."""
        providers = TranscriptionProvider.get_providers()

        self.assertLoggedIn("openai present", "OpenAI", providers)

    def test_rate_limit_reaches_client(self):
        """Provider rate limits flow into the transcription client."""
        provider = OpenAITranscriptionProvider(SettingsType({'api_key': 'k', 'rate_limit': 30.0}))
        client = provider.GetTranscriptionClient(SettingsType())

        self.assertLoggedEqual("client limit", 30.0, client.rate_limit)

    def test_rate_limit_unlimited_by_default(self):
        """No pacing unless the user opts in."""
        provider = OpenAITranscriptionProvider(SettingsType({'api_key': 'k'}))
        client = provider.GetTranscriptionClient(SettingsType())

        self.assertLoggedEqual("no limit", None, client.rate_limit)

    def test_progressive_options_without_key(self):
        """Only the key shows until one is set."""
        with patch.dict(os.environ, {'OPENAI_API_KEY': ''}):
            provider = OpenAITranscriptionProvider(SettingsType())
            options = provider.GetOptions(provider.settings)

            self.assertLoggedEqual("only api_key", ['api_key'], sorted(options.keys()))

    def test_progressive_options_with_key(self):
        """A non-empty key unlocks the full schema."""
        provider = OpenAITranscriptionProvider(SettingsType({'api_key': 'k'}))
        options = provider.GetOptions(provider.settings)

        for key in ('api_key', 'model', 'language', 'request_timeout', 'rate_limit'):
            self.assertLoggedIn(f"{key} option", key, options)

    def test_advanced_settings_match_schema(self):
        """Advanced keys must exist in the options schema, or filtering silently misses."""
        provider = OpenAITranscriptionProvider(SettingsType({'api_key': 'k'}))
        options = provider.GetOptions(provider.settings)

        unknown = [key for key in provider.advanced_settings if key not in options]
        self.assertLoggedEqual("no stale advanced keys", [], unknown)

    def test_language_resolves_to_iso_code(self):
        """Whisper takes ISO 639-1 codes: names and regional tags reduce to the language."""
        provider = OpenAITranscriptionProvider(SettingsType({'api_key': 'k'}))

        self.assertLoggedIsNone("no hint", provider.ResolveLanguageCode(""))
        self.assertLoggedEqual("english name", "zh", provider.ResolveLanguageCode("Chinese"))
        self.assertLoggedEqual("regional tag", "en", provider.ResolveLanguageCode("en-US"))
        self.assertLoggedEqual("native name", "ja", provider.ResolveLanguageCode("\u65e5\u672c\u8a9e"))

        with self.assertRaises(SubtitleError):
            provider.ResolveLanguageCode("Klingon")

        provider.settings['language'] = 'Klingon'
        self.assertLoggedIsNotNone("unknown hint warns", provider.LanguageWarning())


class TestOpenAITranscription(LoggedTestCase):
    def _provider(self, model : str = "whisper-1"):
        return OpenAITranscriptionProvider(SettingsType({'api_key': 'test-key', 'model': model}))

    def test_diarized_segments_parsed(self):
        """diarized_json segments carry speaker labels and timings."""

        payload = {
            'text': 'hello hi',
            'segments': [
                {'speaker': 'A', 'text': 'hello', 'start': 0.9, 'end': 1.5},
                {'speaker': 'B', 'text': 'hi', 'start': 2.0, 'end': 2.7},
            ],
        }
        text, parts = parse_diarized_payload(payload)

        self.assertLoggedEqual("text", "hello hi", text)
        self.assertLoggedEqual("part count", 2, len(parts))
        self.assertLoggedEqual("first speaker", "A", parts[0].speaker)
        self.assertLoggedEqual("second start", timedelta(seconds=2.0), parts[1].start)

    def test_diarized_request_fields(self):
        """Diarize model posts diarized_json with auto chunking."""
        provider = self._provider("gpt-4o-transcribe-diarize")
        client = provider.GetTranscriptionClient(SettingsType())

        with patch('httpx.Client') as mock_client:
            post = mock_client.return_value.__enter__.return_value.post
            mock_response = Mock()
            mock_response.is_error = False
            mock_response.status_code = 200
            mock_response.text = ('{"text": "hi", "segments": ['
                                  '{"speaker": "A", "text": "hi", "start": 0.0, "end": 1.0}]}')
            post.return_value = mock_response
            result = client.TranscribeChunk(b"fake-audio", "wav")

        sent = post.call_args.kwargs['files']
        self.assertLoggedEqual("diarized format", "diarized_json", sent['response_format'][1])
        self.assertLoggedEqual("auto chunking", "auto", sent['chunking_strategy'][1])
        self.assertLoggedEqual("part count", 1, len(result.parts))
        self.assertLoggedEqual("part speaker", "A", result.parts[0].speaker)

    def test_whisper_request_fields(self):
        """Whisper posts verbose word timestamps, never diarized_json."""
        provider = self._provider("whisper-1")
        client = provider.GetTranscriptionClient(SettingsType())

        with patch('httpx.Client') as mock_client:
            post = mock_client.return_value.__enter__.return_value.post
            mock_response = Mock()
            mock_response.is_error = False
            mock_response.status_code = 200
            mock_response.text = ('{"text": "hi", "words": ['
                                  '{"word": "hi", "start": 0.0, "end": 0.5}]}')
            post.return_value = mock_response
            result = client.TranscribeChunk(b"fake-audio", "wav")

        sent = post.call_args.kwargs['files']
        self.assertLoggedEqual("verbose format", "verbose_json", sent['response_format'][1])
        self.assertLoggedEqual("word granularity", "word", sent['timestamp_granularities[]'][1])
        self.assertLoggedEqual("word count", 1, len(result.words))

    def test_untimed_models_rejected(self):
        """Models without timings are refused at validation, not mid-run."""
        for model in ('gpt-transcribe', 'gpt-4o-transcribe', 'gpt-4o-mini-transcribe'):
            provider = self._provider(model)

            self.assertLoggedEqual(f"invalid {model}", False, provider.ValidateSettings())

    def test_timed_models_validate(self):
        """Timed models pass validation with an API key."""
        for model in ('whisper-1', 'gpt-4o-transcribe-diarize'):
            provider = self._provider(model)

            self.assertLoggedEqual(f"valid {model}", True, provider.ValidateSettings())

    def test_diarization_flag(self):
        """Only the diarize model advertises speaker labels."""
        diarized = self._provider("gpt-4o-transcribe-diarize").GetTranscriptionClient(SettingsType())
        plain = self._provider("whisper-1").GetTranscriptionClient(SettingsType())

        self.assertLoggedEqual("diarize model", True, diarized.supports_diarization)
        self.assertLoggedEqual("whisper model", False, plain.supports_diarization)

if __name__ == '__main__':
    unittest.main()
