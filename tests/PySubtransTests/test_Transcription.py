import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import Mock, patch

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.SettingsType import GuiSettingsType, SettingsType
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.Subtitles import Subtitles
from PySubtrans.Transcription.AudioExtractor import AudioChunk, AudioChunker, AudioExtractor
from PySubtrans.Transcription.TranscriptionAligner import WordTiming
from PySubtrans.Transcription.TranscriptionClient import TranscriptionClient
from PySubtrans.Transcription.TranscriptionCoordinator import AudioTrackInfo, TranscriptionCoordinator
from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionResult, TranscriptionSegment


class FakeTranscriptionClient(TranscriptionClient):
    def __init__(self, settings : SettingsType|None = None, texts : list[str]|None = None,
                 words : list[WordTiming]|None = None, timestamps : bool = True):
        super().__init__(settings or SettingsType())
        self.texts : list[str] = texts if texts is not None else ["hello world"]
        self.words : list[WordTiming] = words or []
        self.timed : bool = timestamps
        self.calls : int = 0

    @property
    def supports_timestamps(self) -> bool:
        """Test-controlled capability flag."""
        return self.timed

    def _transcribe_chunk(self, audio_bytes : bytes, audio_format : str, language : str|None) -> TranscriptionResult:
        self.calls += 1
        text = self.texts[(self.calls - 1) % len(self.texts)] if self.texts else ""
        return TranscriptionResult(text=text, language=language, words=list(self.words))


def _ffmpeg_available() -> bool:
    return bool(shutil.which('ffmpeg') and shutil.which('ffprobe'))


def _make_tone_silence_wav(path : str) -> None:    # 4s tone, 2s silence, 4s tone at 16kHz mono
    subprocess.run(
        ['ffmpeg', '-y', '-v', 'error',
         '-f', 'lavfi', '-i', 'sine=frequency=440:duration=4',
         '-f', 'lavfi', '-i', 'aevalsrc=0:d=2',
         '-f', 'lavfi', '-i', 'sine=frequency=660:duration=4',
         '-filter_complex', '[0:a][1:a][2:a]concat=n=3:v=0:a=1',
         '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', path],
        check=True, timeout=60
    )


class FakeTranscriptionProvider(TranscriptionProvider):
    """In-test transcription provider with canned client responses."""
    name = "Fake Transcription"

    def __init__(self, settings : SettingsType|None = None, texts : list[str]|None = None,
                 words : list[WordTiming]|None = None, timestamps : bool = True):
        super().__init__(self.name, settings or SettingsType())
        self.texts : list[str]|None = texts
        self.words : list[WordTiming]|None = words
        self.timed : bool = timestamps
        self.client : FakeTranscriptionClient|None = None

    def GetAvailableModels(self) -> list[str]:
        """Static model list for tests."""
        return ['fake-model']

    def GetTranscriptionClient(self, settings : SettingsType) -> TranscriptionClient:
        """Client returning the canned responses."""
        self.client = FakeTranscriptionClient(settings, self.texts, self.words, self.timed)
        return self.client

    def GetOptions(self, settings : SettingsType) -> GuiSettingsType:
        """Settings schema exercising text and dropdown widgets."""
        return {
            'model': (self.available_models, "Model to use"),
            'language': (str, "Language hint"),
        }


class TestTranscriptionSegment(LoggedTestCase):
    def test_segment_defaults(self):
        """Segments carry timings, text and empty speaker by default."""
        segment = TranscriptionSegment(start=timedelta(seconds=1), end=timedelta(seconds=3), text="hi")

        self.assertLoggedEqual("start", timedelta(seconds=1), segment.start)
        self.assertLoggedEqual("end", timedelta(seconds=3), segment.end)
        self.assertLoggedEqual("text", "hi", segment.text)
        self.assertLoggedEqual("speaker default", None, segment.speaker)


class TestTranscriptionProviderRegistry(LoggedTestCase):
    def test_fake_provider_registered(self):
        """Providers register through __subclasses__ discovery."""
        providers = TranscriptionProvider.get_providers()

        self.assertLoggedIn("provider registry", "Fake Transcription", providers)

    def test_create_unknown_provider_raises(self):
        """Unknown provider names raise a clear error."""
        with self.assertRaises(ValueError):
            TranscriptionProvider.create_provider("No Such Provider", SettingsType())

    def test_fake_provider_options(self):
        """Provider options describe settings for dynamic dialogs."""
        provider = FakeTranscriptionProvider()
        options = provider.GetOptions(SettingsType())

        self.assertLoggedIn("model option", "model", options)
        self.assertLoggedIn("language option", "language", options)

    def test_fake_provider_validation(self):
        """Base validation passes without required settings."""
        provider = FakeTranscriptionProvider()

        self.assertLoggedEqual("valid by default", True, provider.ValidateSettings())


class TestAudioChunker(LoggedTestCase):
    def test_plan_scenes_on_synthetic_audio(self):
        """Silence in the middle of audio produces two coherent chunks."""
        if not _ffmpeg_available():
            self.skipTest("ffmpeg not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            wav_path = os.path.join(tmpdir, "tones.wav")
            _make_tone_silence_wav(wav_path)

            chunker = AudioChunker(SettingsType({'min_chunk_seconds': 2.0, 'max_chunk_seconds': 30.0}))
            chunks = chunker.PlanChunks(wav_path)

        self.assertLoggedEqual("scene count", 2, len(chunks))
        self.assertLoggedEqual("first scene start", timedelta(seconds=0), chunks[0].start)
        self.assertLoggedGreater("second scene start", chunks[1].start.total_seconds(), 3.0)
        self.assertLoggedGreater("coverage", chunks[1].end.total_seconds(), 9.0)

    def test_lookahead_extends_past_cap_to_silence(self):
        """Over-long stretches extend to nearby silence instead of hard-cutting."""
        if not _ffmpeg_available():
            self.skipTest("ffmpeg not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            wav_path = os.path.join(tmpdir, "long.wav")
            subprocess.run(
                ['ffmpeg', '-y', '-v', 'error',
                 '-f', 'lavfi', '-i', 'sine=frequency=440:duration=65',
                 '-f', 'lavfi', '-i', 'aevalsrc=0:d=2',
                 '-f', 'lavfi', '-i', 'sine=frequency=660:duration=5',
                 '-filter_complex', '[0:a][1:a][2:a]concat=n=3:v=0:a=1',
                 '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', wav_path],
                check=True, timeout=120
            )
            chunker = AudioChunker(SettingsType({
                'min_chunk_seconds': 2.0, 'max_chunk_seconds': 60.0, 'lookahead_seconds': 30.0}))
            chunks = chunker.PlanChunks(wav_path)

        self.assertLoggedEqual("scene count", 2, len(chunks))
        self.assertLoggedGreater("first cut past the cap", chunks[0].end.total_seconds(), 60.0)
        self.assertLoggedGreater("cut near silence", 66.5, chunks[0].end.total_seconds())

    def test_max_chunk_cap(self):
        """Long stretches without silence are hard-split at the cap."""
        if not _ffmpeg_available():
            self.skipTest("ffmpeg not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            wav_path = os.path.join(tmpdir, "tone.wav")
            subprocess.run(
                ['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi',
                 '-i', 'sine=frequency=440:duration=12',
                 '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', wav_path],
                check=True, timeout=60
            )
            chunker = AudioChunker(SettingsType({'min_chunk_seconds': 2.0, 'max_chunk_seconds': 5.0}))
            chunks = chunker.PlanChunks(wav_path)

        self.assertLoggedGreater("chunk count", len(chunks), 1)
        for chunk in chunks:
            self.assertLoggedGreater(
                "chunk within cap",
                5.5, (chunk.end - chunk.start).total_seconds()
            )


class TestQwenResultParsing(LoggedTestCase):
    def test_parse_timestamps(self):
        """qwen-asr results extract text, language and word timings."""
        from PySubtrans.Transcription.Providers.Provider_QwenLocal import parse_qwen_result

        unit = type("Unit", (), {'text': 'hello', 'start_time': 0.5, 'end_time': 0.9})()
        result = type("Result", (), {'text': 'hello', 'language': 'Chinese', 'time_stamps': [unit]})()
        text, language, words = parse_qwen_result(result)

        self.assertLoggedEqual("text", "hello", text)
        self.assertLoggedEqual("language", "Chinese", language)
        self.assertLoggedEqual("word count", 1, len(words))
        self.assertLoggedEqual("word start", timedelta(seconds=0.5), words[0].start)

    def test_parse_flat_result(self):
        """Results without timestamps parse to text-only."""
        from PySubtrans.Transcription.Providers.Provider_QwenLocal import parse_qwen_result

        result = type("Result", (), {'text': 'hi', 'language': None, 'time_stamps': None})()
        text, language, words = parse_qwen_result(result)

        self.assertLoggedEqual("text", "hi", text)
        self.assertLoggedEqual("language", None, language)
        self.assertLoggedEqual("word count", 0, len(words))

    def test_qwen_local_absent_without_package(self):
        """Provider stays unregistered when qwen-asr is not installed."""
        import importlib.util

        if importlib.util.find_spec("qwen_asr"):
            self.skipTest("qwen-asr installed")
        providers = TranscriptionProvider.get_providers()

        self.assertLoggedIn("fake present", "Fake Transcription", providers)
        self.assertLoggedEqual("qwen absent", False, "Qwen Local" in providers)


def _word(text : str, start : float, end : float) -> WordTiming:
    return WordTiming(text=text, start=timedelta(seconds=start), end=timedelta(seconds=end))


class TestOpenRouterParsing(LoggedTestCase):
    def test_verbose_words_with_speakers(self):
        """Word timings and speaker labels parse from verbose responses."""
        from PySubtrans.Transcription.Providers.Provider_OpenRouter import parse_transcription_payload

        payload = {
            'text': 'hello world',
            'language': 'en',
            'words': [
                {'word': 'hello', 'start': 0.5, 'end': 0.9, 'speaker': 0},
                {'word': 'world', 'start': 1.0, 'end': 1.4, 'speaker': 1},
            ],
        }
        text, language, _parts, words = parse_transcription_payload(payload)

        self.assertLoggedEqual("text", "hello world", text)
        self.assertLoggedEqual("language", "en", language)
        self.assertLoggedEqual("word count", 2, len(words))
        self.assertLoggedEqual("first speaker", "0", words[0].speaker)
        self.assertLoggedEqual("second speaker", "1", words[1].speaker)

    def test_speaker_change_splits_lines(self):
        """Speaker turns break subtitle lines and label them."""
        from PySubtrans.Transcription.Providers.Provider_OpenRouter import parse_transcription_payload

        payload = {
            'text': 'yes no',
            'words': [
                {'word': 'yes', 'start': 0.0, 'end': 0.5, 'speaker': 'A'},
                {'word': 'no', 'start': 0.6, 'end': 1.0, 'speaker': 'B'},
            ],
        }
        text, _detected_language, _parts, words = parse_transcription_payload(payload)

        provider = FakeTranscriptionProvider()
        coordinator = TranscriptionCoordinator(provider, SettingsType())
        chunk = AudioChunk(start=timedelta(seconds=10), end=timedelta(seconds=20))
        segment = TranscriptionSegment(start=chunk.start, end=chunk.end, text=text, words=words)
        lines = coordinator._lines_for_segment(segment)

        self.assertLoggedEqual("line count", 2, len(lines))
        self.assertLoggedEqual("first speaker", "A", lines[0].speaker)
        self.assertLoggedEqual("second speaker", "B", lines[1].speaker)

    def test_segments_without_words(self):
        """Segments parse when word timings are absent."""
        from PySubtrans.Transcription.Providers.Provider_OpenRouter import parse_transcription_payload

        payload = {
            'text': 'first second',
            'segments': [
                {'text': 'first', 'start': 0.0, 'end': 2.0, 'speaker': 'A'},
                {'text': 'second', 'start': 2.5, 'end': 4.0},
            ],
        }
        _text, _language, parts, words = parse_transcription_payload(payload)

        self.assertLoggedEqual("part count", 2, len(parts))
        self.assertLoggedEqual("part speaker", "A", parts[0].speaker)
        self.assertLoggedEqual("no speaker", None, parts[1].speaker)
        self.assertLoggedEqual("word count", 0, len(words))

    def test_malformed_entries_skipped(self):
        """Invalid segments and words never produce degenerate lines."""
        from PySubtrans.Transcription.Providers.Provider_OpenRouter import parse_transcription_payload

        payload = {
            'text': 'ok',
            'segments': [{'text': '', 'start': 0.0, 'end': 1.0}, 'junk', {'text': 'ok', 'start': 5.0, 'end': 4.0}],
            'words': [{'word': 'ok', 'start': 'soon', 'end': 1.0}],
        }
        text, _language, parts, words = parse_transcription_payload(payload)

        self.assertLoggedEqual("text", "ok", text)
        self.assertLoggedEqual("part count", 0, len(parts))
        self.assertLoggedEqual("word count", 0, len(words))


class TestOpenRouterCatalog(LoggedTestCase):
    def _provider(self):
        from PySubtrans.Transcription.Providers.Provider_OpenRouter import OpenRouterTranscriptionProvider
        return OpenRouterTranscriptionProvider(SettingsType({
            'server_address': 'http://127.0.0.1:9/v1', 'api_key': 'test-key',
        }))

    def _mock_get(self, text : str, is_error : bool = False):
        response = Mock()
        response.is_error = is_error
        response.status_code = 500 if is_error else 200
        response.text = text
        return response

    def test_empty_catalog_body_falls_back(self):
        """Empty catalog responses degrade without raising anything."""
        provider = self._provider()

        with patch('httpx.Client') as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = self._mock_get("")
            models = provider.GetAvailableModels()

        self.assertLoggedIn("fallback model", "openai/whisper-large-v3", models)

    def test_malformed_catalog_falls_back(self):
        """Non-JSON catalog responses degrade without raising anything."""
        provider = self._provider()

        with patch('httpx.Client') as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = self._mock_get("not json{")
            models = provider.GetAvailableModels()

        self.assertLoggedIn("fallback model", "openai/whisper-large-v3", models)

    def test_html_catalog_body_falls_back(self):
        """HTML error pages degrade without raising anything."""
        provider = self._provider()

        with patch('httpx.Client') as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = self._mock_get(
                "<!DOCTYPE html><html>Bad Gateway</html>")
            models = provider.GetAvailableModels()

        self.assertLoggedIn("fallback model", "openai/whisper-large-v3", models)

    def test_unreachable_catalog_falls_back(self):
        """Unreachable catalogs degrade without raising anything."""
        provider = self._provider()

        with patch('httpx.Client', side_effect=Exception("unreachable")):
            models = provider.GetAvailableModels()

        self.assertLoggedIn("fallback model", "openai/whisper-large-v3", models)


class TestOpenRouterClient(LoggedTestCase):
    def _client(self, model : str = "openai/whisper-large-v3", diarize : bool = False):
        from PySubtrans.Transcription.Providers.Provider_OpenRouter import OpenRouterTranscriptionClient
        return OpenRouterTranscriptionClient(SettingsType({
            'server_address': 'http://127.0.0.1:9/v1', 'api_key': 'test-key',
            'model': model, 'diarize': diarize,
        }))

    def test_usage_cost_and_duration_parsed(self):
        """Usage blocks attach duration and billed cost to the result."""
        from PySubtrans.Transcription.Providers.Provider_OpenRouter import OpenRouterTranscriptionClient
        client = OpenRouterTranscriptionClient(SettingsType({
            'server_address': 'http://127.0.0.1:9/v1', 'api_key': 'test-key',
            'model': 'openai/whisper-large-v3',
        }))

        with patch('httpx.Client') as mock_client:
            mock_response = mock_client.return_value.__enter__.return_value.post.return_value
            mock_response.status_code = 200
            mock_response.is_error = False
            mock_response.text = ('{"text": "hi", "language": "en", "duration": 9.2,'
                                  ' "usage": {"cost": 0.000508, "seconds": 9.2}}')
            result = client.TranscribeChunk(b"fake-audio", "wav", "en")

        self.assertLoggedEqual("duration", timedelta(seconds=9.2), result.duration)
        self.assertLoggedEqual("cost", 0.000508, result.cost)

    def test_no_speech_prob_maps_to_confidence(self):
        """no_speech_prob surfaces as segment confidence for review."""
        from PySubtrans.Transcription.Providers.Provider_OpenRouter import parse_transcription_payload

        payload = {
            'text': 'hmm',
            'segments': [{'text': 'hmm', 'start': 1.0, 'end': 2.0, 'no_speech_prob': 0.85}],
        }
        _text, _language, parts, _words = parse_transcription_payload(payload)

        self.assertLoggedEqual("part count", 1, len(parts))
        assert parts[0].confidence is not None  # Type narrowing for PyLance
        self.assertLoggedGreater("low confidence", 0.2, parts[0].confidence)
        self.assertLoggedGreater("below threshold", 0.4, parts[0].confidence)

    def test_client_capability_flags(self):
        """OpenRouter negotiates timestamps; diarization follows the toggle."""
        timed = self._client()
        silent = self._client(diarize=False)

        self.assertLoggedEqual("timestamps negotiated", True, timed.supports_timestamps)
        self.assertLoggedEqual("no diarization by default", False, silent.supports_diarization)

        diarized = self._client(model="microsoft/mai-transcribe-2", diarize=True)
        self.assertLoggedEqual("diarization requested", True, diarized.supports_diarization)

    def test_html_transcription_body_readable_error(self):
        """HTML error pages surface as readable errors, not decode failures."""
        client = self._client()

        with patch('httpx.Client') as mock_client:
            mock_response = mock_client.return_value.__enter__.return_value.post.return_value
            mock_response.status_code = 200
            mock_response.is_error = False
            mock_response.text = "<!DOCTYPE html><html>Bad Gateway</html>"
            with self.assertRaisesRegex(SubtitleError, "non-JSON response"):
                client.TranscribeChunk(b"fake-audio", "wav", "en")

    def test_empty_text_returned_not_raised(self):
        """Empty transcripts return quietly for the coordinator to skip."""
        client = self._client()

        with patch('httpx.Client') as mock_client:
            mock_response = mock_client.return_value.__enter__.return_value.post.return_value
            mock_response.status_code = 200
            mock_response.is_error = False
            mock_response.text = '{"text": "", "usage": {"cost": 0.0001}}'
            result = client.TranscribeChunk(b"fake-audio", "wav", "en")

        self.assertLoggedEqual("empty text", "", result.text)

    def test_verbose_rejection_fails_fast(self):
        """Providers rejecting verbose output fail fast instead of billing twice."""
        client = self._client()

        with patch('httpx.Client') as mock_client:
            post = mock_client.return_value.__enter__.return_value.post
            verbose = Mock()
            verbose.status_code = 400
            verbose.is_error = True
            verbose.text = '{"error": "verbose_json not supported"}'
            post.side_effect = [verbose]
            with self.assertRaisesRegex(SubtitleError, "does not support"):
                client.TranscribeChunk(b"fake-audio", "wav", "en")

        self.assertLoggedEqual("single request", 1, post.call_count)

    def test_diarize_mapping_azure(self):
        """Diarize maps onto Azure options for Microsoft models."""
        client = self._client(model="microsoft/mai-transcribe-2", diarize=True)

        options = client._diarize_options()

        self.assertLoggedIn("azure options", "azure", options)

    def test_diarize_mapping_deepgram(self):
        """Diarize maps onto Deepgram options."""
        client = self._client(model="deepgram/nova-3", diarize=True)

        options = client._diarize_options()

        self.assertLoggedIn("deepgram options", "deepgram", options)

    def test_diarize_unmapped_model(self):
        """Unmapped models request without diarization options."""
        client = self._client(model="openai/whisper-large-v3", diarize=True)

        options = client._diarize_options()

        self.assertLoggedEqual("empty options", {}, options)


class TestOpenAITranscription(LoggedTestCase):
    def _provider(self, model : str = "whisper-1"):
        from PySubtrans.Transcription.Providers.Provider_OpenAI import OpenAITranscriptionProvider
        return OpenAITranscriptionProvider(SettingsType({'api_key': 'test-key', 'model': model}))

    def test_diarized_segments_parsed(self):
        """diarized_json segments carry speaker labels and timings."""
        from PySubtrans.Transcription.Providers.Provider_OpenAI import parse_diarized_payload

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
            result = client.TranscribeChunk(b"fake-audio", "wav", "en")

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
            result = client.TranscribeChunk(b"fake-audio", "wav", "en")

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


class TestWordGrouping(LoggedTestCase):
    def _coordinator(self):
        provider = FakeTranscriptionProvider()
        return TranscriptionCoordinator(provider, SettingsType({'language': 'Chinese'}))

    def _scene_lines(self, coordinator, text : str, words : list[WordTiming], language : str|None = "Chinese"):
        chunk = AudioChunk(start=timedelta(seconds=100), end=timedelta(seconds=160))
        segment = TranscriptionSegment(start=chunk.start, end=chunk.end, text=text, language=language, words=words)
        return coordinator._lines_for_segment(segment)

    def test_aligned_words_group_into_true_lines(self):
        """Line boundaries and timings come from aligned words."""
        words = [_word("師傅", 0.0, 0.5), _word("來了", 0.5, 1.0),
                 _word("。", 1.0, 1.1), _word("他們", 3.0, 3.5), _word("騎馬", 3.5, 4.0)]
        lines = self._scene_lines(self._coordinator(), "師傅來了。他們騎馬", words)

        self.assertLoggedEqual("line count", 2, len(lines))
        self.assertLoggedEqual("first start", timedelta(seconds=100), lines[0].start)
        self.assertLoggedEqual("first end", timedelta(seconds=101.1), lines[0].end)
        self.assertLoggedEqual("second start", timedelta(seconds=103), lines[1].start)
        self.assertLoggedEqual("no fabrication", timedelta(seconds=104), lines[1].end)

    def test_no_words_stays_scene_line(self):
        """Untimed scenes stay one honest line over the chunk span."""
        coordinator = self._coordinator()
        lines = self._scene_lines(coordinator, "some text", [], language="Thai")

        self.assertLoggedEqual("line count", 1, len(lines))
        self.assertLoggedEqual("span preserved", timedelta(seconds=160), lines[0].end)

    def test_latin_words_spaced(self):
        """Latin words join with spaces, CJK without."""
        words = [_word("Hello", 0.0, 0.5), _word("world", 0.6, 1.0)]
        coordinator = self._coordinator()
        lines = self._scene_lines(coordinator, "Hello world", words, language="English")

        self.assertLoggedEqual("line count", 1, len(lines))
        self.assertLoggedEqual("spaced text", "Hello world", lines[0].text)


class TestSettingsNamespaces(LoggedTestCase):
    def _options(self):
        from PySubtrans.Options import Options
        options = Options()
        options.provider_settings['OpenRouter'] = SettingsType({
            'api_key': 'shared-key',
            'server_address': 'https://openrouter.ai/api/',
            'model': 'Some Translation Model',
        })
        return options

    def test_credentials_shared_endpoints_not(self):
        """Only api_key/proxy travel across capabilities, never endpoints."""
        options = self._options()
        resolved = TranscriptionCoordinator.ResolveProviderSettings(
            "OpenRouter", SettingsType(), options)

        self.assertLoggedEqual("shared key", "shared-key", resolved.get_str('api_key'))
        self.assertLoggedEqual("no shared server", None, resolved.get_str('server_address'))
        self.assertLoggedEqual("no shared model", None, resolved.get_str('model'))

    def test_own_namespace_wins(self):
        """Saved transcription settings take precedence over shared ones."""
        options = self._options()
        options.provider_settings['OpenRouter Transcription'] = SettingsType({
            'model': 'openai/whisper-large-v3',
        })
        resolved = TranscriptionCoordinator.ResolveProviderSettings(
            "OpenRouter", SettingsType(), options)

        self.assertLoggedEqual("own model", "openai/whisper-large-v3", resolved.get_str('model'))
        self.assertLoggedEqual("shared key", "shared-key", resolved.get_str('api_key'))

    def test_settings_key_format(self):
        """Transcription namespaces are clearly separated."""
        self.assertLoggedEqual(
            "key format", "OpenRouter Transcription",
            TranscriptionCoordinator.SettingsKey("OpenRouter"))


class TestSilenceGate(LoggedTestCase):
    def _coordinator(self, texts : list[str]|None = None):
        provider = FakeTranscriptionProvider(SettingsType(), texts)
        return TranscriptionCoordinator(provider, SettingsType()), provider

    def _silent_wav(self, seconds : float = 1.0) -> bytes:
        import array
        import io
        import wave

        samples = array.array('h', [0] * int(16000 * seconds))
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(samples.tobytes())
        return buffer.getvalue()

    def _tone_wav(self, seconds : float = 1.0) -> bytes:
        import array
        import io
        import math
        import wave

        samples = array.array('h', (int(10000 * math.sin(2.0 * math.pi * 440.0 * t / 16000))
                                    for t in range(int(16000 * seconds))))
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(samples.tobytes())
        return buffer.getvalue()

    def test_silent_audio_detected(self):
        """Digital silence never reaches the transcription backend."""
        extractor = AudioExtractor(SettingsType())

        self.assertLoggedEqual("silent", True, extractor.IsSilent(self._silent_wav()))
        self.assertLoggedEqual("tone", False, extractor.IsSilent(self._tone_wav()))
        self.assertLoggedEqual("garbage", False, extractor.IsSilent(b"not-a-wav"))

    def test_silent_chunks_skipped_before_request(self):
        """Silent chunks cost no requests and yield no lines."""
        coordinator, provider = self._coordinator(["audible"])
        coordinator.chunker.PlanChunks = lambda media_path, track=0: [  # type: ignore[method-assign]
            AudioChunk(start=timedelta(seconds=0), end=timedelta(seconds=2)),
        ]
        coordinator.extractor.ReadChunkBytes = lambda *args, **kwargs: self._silent_wav()  # type: ignore[method-assign]

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            with self.assertRaisesRegex(SubtitleError, "No timed"):
                coordinator.TranscribeMedia(media.name)

        assert provider.client is not None  # Type narrowing for PyLance
        self.assertLoggedEqual("no requests sent", 0, provider.client.calls)


class TestTranscriptionCoordinator(LoggedTestCase):
    def _coordinator(self, texts : list[str]|None = None, words : list[WordTiming]|None = None):
        provider = FakeTranscriptionProvider(SettingsType(), texts, words)
        coordinator = TranscriptionCoordinator(provider, SettingsType({'min_chunk_seconds': 1.0}))
        return coordinator, provider

    def test_transcribe_media_builds_subtitles(self):
        """Scenes with word timings become truly timed subtitle lines."""
        coordinator, provider = self._coordinator(
            ["first line", "second line"], [_word("w", 0.0, 1.0)])
        coordinator.chunker.PlanChunks = lambda media_path, track=0: [  # type: ignore[method-assign]
            AudioChunk(start=timedelta(seconds=0), end=timedelta(seconds=4)),
            AudioChunk(start=timedelta(seconds=6), end=timedelta(seconds=10)),
        ]
        coordinator.extractor.ReadChunkBytes = lambda *args, **kwargs: b"fake"  # type: ignore[method-assign]

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            subtitles = coordinator.TranscribeMedia(media.name)

        self.assertLoggedIsInstance("subtitles type", subtitles, Subtitles)
        self.assertLoggedEqual("line count", 2, subtitles.linecount)
        assert subtitles.originals is not None  # Type narrowing for PyLance
        self.assertLoggedEqual("first start", timedelta(seconds=0), subtitles.originals[0].start)
        self.assertLoggedEqual("second start", timedelta(seconds=6), subtitles.originals[1].start)
        assert provider.client is not None  # Type narrowing for PyLance
        self.assertLoggedEqual("client calls", 2, provider.client.calls)

    def test_gate_refuses_untimed_provider(self):
        """Providers without timings are refused before spending anything."""
        provider = FakeTranscriptionProvider(SettingsType(), ["some text"], timestamps=False)
        coordinator = TranscriptionCoordinator(provider, SettingsType())

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            with self.assertRaisesRegex(SubtitleError, "Fake Transcription"):
                coordinator.TranscribeMedia(media.name)

    def test_untimed_results_kept_as_scene_lines(self):
        """Paid-for flat text is kept over true chunk spans, not thrown away."""
        coordinator, _ = self._coordinator(["first scene", "second scene"])
        coordinator.chunker.PlanChunks = lambda media_path, track=0: [  # type: ignore[method-assign]
            AudioChunk(start=timedelta(seconds=0), end=timedelta(seconds=2)),
            AudioChunk(start=timedelta(seconds=2), end=timedelta(seconds=4)),
        ]
        coordinator.extractor.ReadChunkBytes = lambda *args, **kwargs: b"fake"  # type: ignore[method-assign]

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            subtitles = coordinator.TranscribeMedia(media.name)

        self.assertLoggedEqual("line count", 2, subtitles.linecount)
        assert subtitles.originals is not None  # Type narrowing for PyLance
        self.assertLoggedEqual("second span", timedelta(seconds=4), subtitles.originals[1].end)

    def test_no_speech_raises(self):
        """Media with nothing transcribable raises instead of empty project."""
        coordinator, _ = self._coordinator(["", "   "])
        coordinator.chunker.PlanChunks = lambda media_path, track=0: [  # type: ignore[method-assign]
            AudioChunk(start=timedelta(seconds=0), end=timedelta(seconds=2)),
        ]
        coordinator.extractor.ReadChunkBytes = lambda *args, **kwargs: b"fake"  # type: ignore[method-assign]

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            with self.assertRaises(SubtitleError):
                coordinator.TranscribeMedia(media.name)

    def test_segment_callback_receives_each_scene(self):
        """Per-chunk callback fires with timings for live progress display."""
        coordinator, _ = self._coordinator(["first line", "second line"], [_word("w", 0.0, 1.0)])
        coordinator.chunker.PlanChunks = lambda media_path, track=0: [  # type: ignore[method-assign]
            AudioChunk(start=timedelta(seconds=0), end=timedelta(seconds=4)),
            AudioChunk(start=timedelta(seconds=6), end=timedelta(seconds=10)),
        ]
        coordinator.extractor.ReadChunkBytes = lambda *args, **kwargs: b"fake"  # type: ignore[method-assign]

        seen : list = []
        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            coordinator.TranscribeMedia(media.name, segment_cb=seen.append)

        self.assertLoggedEqual("callback count", 2, len(seen))
        self.assertLoggedEqual("second start", timedelta(seconds=6), seen[1].start)

    def test_engine_words_grouped_into_lines(self):
        """Word timings from the engine produce truly timed lines."""
        words = [_word("first", 0.0, 1.0), _word("line", 1.0, 2.0),
                 _word("second", 5.0, 6.0), _word("line", 6.0, 7.0)]
        coordinator, _ = self._coordinator(["first line second line"], words)
        coordinator.chunker.PlanChunks = lambda media_path, track=0: [  # type: ignore[method-assign]
            AudioChunk(start=timedelta(seconds=10), end=timedelta(seconds=20)),
        ]
        coordinator.extractor.ReadChunkBytes = lambda *args, **kwargs: b"fake"  # type: ignore[method-assign]

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            subtitles = coordinator.TranscribeMedia(media.name)

        self.assertLoggedEqual("line count", 2, subtitles.linecount)
        assert subtitles.originals is not None  # Type narrowing for PyLance
        self.assertLoggedEqual("first start", timedelta(seconds=10), subtitles.originals[0].start)
        self.assertLoggedEqual("second start", timedelta(seconds=15), subtitles.originals[1].start)

    def test_abort_keeps_partial_results(self):
        """Cancelling keeps billed work instead of throwing it away."""
        coordinator, _ = self._coordinator(["first line", "second line"], [_word("w", 0.0, 1.0)])
        coordinator.chunker.PlanChunks = lambda media_path, track=0: [  # type: ignore[method-assign]
            AudioChunk(start=timedelta(seconds=0), end=timedelta(seconds=4)),
            AudioChunk(start=timedelta(seconds=6), end=timedelta(seconds=10)),
        ]
        coordinator.extractor.ReadChunkBytes = lambda *args, **kwargs: b"fake"  # type: ignore[method-assign]

        def abort_after_first(done : int, total : int) -> None:
            if done >= 1:
                coordinator.Abort()

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            subtitles = coordinator.TranscribeMedia(media.name, progress_cb=abort_after_first)

        self.assertLoggedEqual("partial line count", 1, subtitles.linecount)

    def test_abort_before_anything_raises(self):
        """Cancelling with nothing transcribed still raises, not empty output."""
        coordinator, _ = self._coordinator(["first line"], [_word("w", 0.0, 1.0)])
        coordinator.chunker.PlanChunks = lambda media_path, track=0: [  # type: ignore[method-assign]
            AudioChunk(start=timedelta(seconds=0), end=timedelta(seconds=4)),
        ]
        coordinator.extractor.ReadChunkBytes = lambda *args, **kwargs: b"fake"  # type: ignore[method-assign]
        coordinator.Abort()

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            with self.assertRaises(SubtitleError):
                coordinator.TranscribeMedia(media.name)

    def test_audio_track_info_label(self):
        """Track descriptors render a readable label."""
        info = AudioTrackInfo(index=1, codec="ac3", language="chi")

        self.assertLoggedEqual("label", "Track 1 - ac3 - chi", str(info))


if __name__ == '__main__':
    unittest.main()
