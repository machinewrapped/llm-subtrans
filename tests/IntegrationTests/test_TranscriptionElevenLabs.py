import os
import unittest
from datetime import timedelta
from unittest.mock import patch

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.SettingsType import SettingsType
from PySubtrans.Transcription.TranscriptionCoordinator import TranscriptionCoordinator
from PySubtrans.Transcription.TranscriptionProvider import OptionsScope, TranscriptionProvider
from PySubtrans.Transcription.Providers.Provider_ElevenLabs import ElevenLabsTranscriptionProvider
from PySubtrans.Transcription.Providers.Clients.ElevenLabsTranscriptionClient import (
    ElevenLabsTranscriptionClient,
    _parse_transcription_payload,
)


class TestElevenLabsProvider(LoggedTestCase):
    def test_registered(self):
        """ElevenLabs always registers (HTTP-only, no SDK)."""
        self.assertLoggedIn("elevenlabs present", "ElevenLabs", TranscriptionProvider.get_providers())

    def test_progressive_options_without_key(self):
        """Only the key shows until one is set."""
        with patch.dict(os.environ, {'ELEVENLABS_API_KEY': ''}):
            provider = ElevenLabsTranscriptionProvider(SettingsType())
            options = provider.GetOptions(provider.settings)

        self.assertLoggedEqual("only api_key", ['api_key'], sorted(options.keys()))

    def test_whole_clip_hides_chunk_options(self):
        """Chunk limits are offered only when the clip is split."""
        whole = ElevenLabsTranscriptionProvider(SettingsType({'api_key': 'k', 'transcribe_whole_clip': True}))
        chunked = ElevenLabsTranscriptionProvider(SettingsType({'api_key': 'k', 'transcribe_whole_clip': False}))

        whole_options = whole.GetOptions(whole.settings, OptionsScope.PER_RUN)
        chunked_options = chunked.GetOptions(chunked.settings, OptionsScope.PER_RUN)

        self.assertLoggedIn("whole clip offered", 'transcribe_whole_clip', whole_options)
        self.assertLoggedNotIn("whole clip hides max chunk", 'max_chunk_seconds', whole_options)
        self.assertLoggedIn("chunked offers max chunk", 'max_chunk_seconds', chunked_options)
        self.assertLoggedIn("chunked offers min chunk", 'min_chunk_seconds', chunked_options)

    def test_zero_max_chunk_requests_whole_clip(self):
        """A maximum chunk length of 0 asks for the whole clip, and leaves usable chunk limits."""
        provider = ElevenLabsTranscriptionProvider(SettingsType({'api_key': 'k', 'max_chunk_seconds': 0.0}))

        self.assertLoggedTrue("whole clip", provider.transcribe_whole_clip)
        self.assertLoggedGreater("max chunk kept usable", provider.settings.get_float('max_chunk_seconds') or 0.0, 0.0)

    def test_explicit_choice_wins_over_zero_max_chunk(self):
        """An explicit choice is kept even when the maximum chunk length is 0."""
        provider = ElevenLabsTranscriptionProvider(SettingsType({
            'api_key': 'k', 'max_chunk_seconds': 0.0, 'transcribe_whole_clip': False}))

        self.assertLoggedFalse("chunked", provider.transcribe_whole_clip)

    def test_coordinator_plans_one_chunk_for_whole_clip(self):
        """The whole media becomes one chunk, without a silence scan."""
        provider = ElevenLabsTranscriptionProvider(SettingsType({'api_key': 'k', 'transcribe_whole_clip': True}))
        coordinator = TranscriptionCoordinator(provider, SettingsType())
        extractor = coordinator.chunker.extractor

        with patch.object(extractor, 'GetDuration', return_value=timedelta(minutes=62)), \
             patch.object(extractor, 'DetectSilencesStream') as detect:
            chunks = coordinator.chunker.PlanChunks('episode.mkv')

        self.assertLoggedEqual("chunk count", 1, len(chunks))
        self.assertLoggedEqual("chunk end", timedelta(minutes=62), chunks[0].end)
        self.assertLoggedEqual("no silence scan", 0, detect.call_count)

    def test_language_resolves_to_iso_code(self):
        """Language names become ISO 639-1 codes."""
        provider = ElevenLabsTranscriptionProvider(SettingsType({'api_key': 'k'}))

        self.assertLoggedEqual("korean", "ko", provider.ResolveLanguageCode("Korean"))
        self.assertLoggedIsNone("no hint", provider.ResolveLanguageCode(None))


class TestElevenLabsClient(LoggedTestCase):
    def _client(self, **settings) -> ElevenLabsTranscriptionClient:
        return ElevenLabsTranscriptionClient(SettingsType({
            'server_address': 'http://127.0.0.1:9/v1', 'api_key': 'test-key', 'model': 'scribe_v2', **settings}))

    def _post(self, client : ElevenLabsTranscriptionClient, reply : str):
        """Transcribe fake audio against a mocked endpoint, returning the result and the post mock."""
        with patch('httpx.Client') as mock_client:
            post = mock_client.return_value.__enter__.return_value.post
            post.return_value.status_code = 200
            post.return_value.is_error = False
            post.return_value.text = reply
            result = client.TranscribeChunk(b"fake-audio", "wav")

        return result, post

    def test_request_fields(self):
        """The request authenticates with xi-api-key and sends the model, hint and switches as form fields."""
        client = self._client(language='ko', diarize=True, audio_events=False)

        _result, post = self._post(client, '{"text": "", "words": []}')

        files = post.call_args.kwargs['files']
        self.assertLoggedEqual("endpoint", 'http://127.0.0.1:9/v1/speech-to-text', post.call_args.args[0])
        self.assertLoggedEqual("api key header", 'test-key', post.call_args.kwargs['headers'].get('xi-api-key'))
        self.assertLoggedEqual("model", 'scribe_v2', files['model_id'][1])
        self.assertLoggedEqual("language", 'ko', files['language_code'][1])
        self.assertLoggedEqual("word timestamps", 'word', files['timestamps_granularity'][1])
        self.assertLoggedEqual("diarize", 'true', files['diarize'][1])
        self.assertLoggedEqual("audio events", 'false', files['tag_audio_events'][1])
        self.assertLoggedIn("audio attached", 'file', files)

    def test_no_language_hint_omits_field(self):
        """Without a hint the language is detected."""
        _result, post = self._post(self._client(), '{"text": "", "words": []}')

        self.assertLoggedNotIn("no language field", 'language_code', post.call_args.kwargs['files'])

    def test_response_parsed(self):
        """Text, language, duration and timed words come back in the result."""
        reply = ('{"text": "hi there", "language_code": "eng", "audio_duration_secs": 9.5, "words": ['
                 '{"text": "hi", "start": 1.0, "end": 1.2, "type": "word", "speaker_id": "speaker_0"},'
                 '{"text": " ", "start": 1.2, "end": 1.3, "type": "spacing", "speaker_id": "speaker_0"},'
                 '{"text": "there", "start": 1.3, "end": 1.6, "type": "word", "speaker_id": "speaker_1"}]}')

        result, _post = self._post(self._client(), reply)

        self.assertLoggedEqual("text", "hi there", result.text)
        self.assertLoggedEqual("language", "eng", result.language)
        self.assertLoggedEqual("duration", timedelta(seconds=9.5), result.duration)
        self.assertLoggedEqual("words", ['hi', 'there'], [word.text for word in result.words or []])
        self.assertLoggedEqual("speakers", ['speaker_0', 'speaker_1'], [word.speaker for word in result.words or []])

    def test_words_filtered(self):
        """Spacing is skipped, audio events and zero-length words are kept, reversed timings are dropped."""
        payload = {
            'text': 'a (laughter) b c',
            'words': [
                {'text': 'a', 'start': 1.0, 'end': 1.2, 'type': 'word'},
                {'text': ' ', 'start': 1.2, 'end': 1.3, 'type': 'spacing'},
                {'text': '(laughter)', 'start': 1.3, 'end': 2.0, 'type': 'audio_event'},
                {'text': 'b', 'start': 2.1, 'end': 2.1, 'type': 'word'},
                {'text': 'c', 'start': 3.0, 'end': 2.9, 'type': 'word'},
            ],
        }
        _text, _language, words = _parse_transcription_payload(payload)

        self.assertLoggedEqual("words kept", ['a', '(laughter)', 'b'], [word.text for word in words])

    def test_empty_result_returned(self):
        """Music or silence is a successful empty result, not an error."""
        result, _post = self._post(self._client(), '{"text": "", "words": []}')

        self.assertLoggedEqual("empty text", "", result.text)


if __name__ == '__main__':
    unittest.main()
