import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import timedelta

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.SettingsType import GuiSettingsType, SettingsType
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.Subtitles import Subtitles
from PySubtrans.Transcription.AudioExtractor import SceneChunk, SceneChunker
from PySubtrans.Transcription.TranscriptionAligner import WordTiming
from PySubtrans.Transcription.TranscriptionClient import TranscriptionClient
from PySubtrans.Transcription.TranscriptionCoordinator import AudioTrackInfo, TranscriptionCoordinator
from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionResult, TranscriptionSegment


class FakeTranscriptionClient(TranscriptionClient):
    def __init__(self, settings : SettingsType|None = None, texts : list[str]|None = None,
                 words : list[WordTiming]|None = None):
        super().__init__(settings or SettingsType())
        self.texts : list[str] = texts if texts is not None else ["hello world"]
        self.words : list[WordTiming] = words or []
        self.calls : int = 0

    def _transcribe_chunk(self, audio_bytes : bytes, audio_format : str, language : str|None) -> TranscriptionResult:
        self.calls += 1
        text = self.texts[(self.calls - 1) % len(self.texts)] if self.texts else ""
        return TranscriptionResult(text=text, language=language, words=list(self.words))


def _ffmpeg_available() -> bool:
    return bool(shutil.which('ffmpeg') and shutil.which('ffprobe'))


def _make_tone_silence_wav(path : str) -> None:
    # 4s tone, 2s silence, 4s tone at 16kHz mono
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
                 words : list[WordTiming]|None = None):
        super().__init__(self.name, settings or SettingsType())
        self.texts : list[str]|None = texts
        self.words : list[WordTiming]|None = words
        self.client : FakeTranscriptionClient|None = None

    def GetAvailableModels(self) -> list[str]:
        """Static model list for tests."""
        return ['fake-model']

    def GetTranscriptionClient(self, settings : SettingsType) -> TranscriptionClient:
        """Client returning the canned responses."""
        self.client = FakeTranscriptionClient(settings, self.texts, self.words)
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


class TestSceneChunker(LoggedTestCase):
    def test_plan_scenes_on_synthetic_audio(self):
        """Silence in the middle of audio produces two coherent scenes."""
        if not _ffmpeg_available():
            self.skipTest("ffmpeg not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            wav_path = os.path.join(tmpdir, "tones.wav")
            _make_tone_silence_wav(wav_path)

            chunker = SceneChunker(SettingsType({'min_chunk_seconds': 2.0, 'max_chunk_seconds': 30.0}))
            chunks = chunker.PlanScenes(wav_path)

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
            chunker = SceneChunker(SettingsType({
                'min_chunk_seconds': 2.0, 'max_chunk_seconds': 60.0, 'lookahead_seconds': 30.0}))
            chunks = chunker.PlanScenes(wav_path)

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
            chunker = SceneChunker(SettingsType({'min_chunk_seconds': 2.0, 'max_chunk_seconds': 5.0}))
            chunks = chunker.PlanScenes(wav_path)

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


class TestWordGrouping(LoggedTestCase):
    def _coordinator(self):
        provider = FakeTranscriptionProvider()
        return TranscriptionCoordinator(provider, SettingsType({'language': 'Chinese'}))

    def _scene_lines(self, coordinator, text : str, words : list[WordTiming], language : str|None = "Chinese"):
        chunk = SceneChunk(start=timedelta(seconds=100), end=timedelta(seconds=160))
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
        """Segments without word timings stay one truthful scene line."""
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


class TestTranscriptionCoordinator(LoggedTestCase):
    def _coordinator(self, texts : list[str]|None = None, words : list[WordTiming]|None = None):
        provider = FakeTranscriptionProvider(SettingsType(), texts, words)
        coordinator = TranscriptionCoordinator(provider, SettingsType({'min_chunk_seconds': 1.0}))
        return coordinator, provider

    def test_transcribe_media_builds_subtitles(self):
        """Each scene becomes a timed subtitle line."""
        coordinator, provider = self._coordinator(["first line", "second line"])
        coordinator.chunker.PlanScenes = lambda media_path, track=0: [  # type: ignore[method-assign]
            SceneChunk(start=timedelta(seconds=0), end=timedelta(seconds=4)),
            SceneChunk(start=timedelta(seconds=6), end=timedelta(seconds=10)),
        ]
        coordinator.extractor.ReadChunkBytes = lambda *args, **kwargs: b"fake"  # type: ignore[method-assign]

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            subtitles = coordinator.TranscribeMedia(media.name)

        self.assertLoggedIsInstance("subtitles type", subtitles, Subtitles)
        self.assertLoggedEqual("line count", 2, subtitles.linecount)
        assert subtitles.originals is not None  # Type narrowing for PyLance
        self.assertLoggedEqual("first text", "first line", subtitles.originals[0].text)
        self.assertLoggedEqual("second start", timedelta(seconds=6), subtitles.originals[1].start)
        assert provider.client is not None  # Type narrowing for PyLance
        self.assertLoggedEqual("client calls", 2, provider.client.calls)

    def test_empty_transcriptions_skipped(self):
        """Scenes with no speech are skipped, not emitted as blank lines."""
        coordinator, _ = self._coordinator(["", "audible"])
        coordinator.chunker.PlanScenes = lambda media_path, track=0: [  # type: ignore[method-assign]
            SceneChunk(start=timedelta(seconds=0), end=timedelta(seconds=2)),
            SceneChunk(start=timedelta(seconds=2), end=timedelta(seconds=4)),
        ]
        coordinator.extractor.ReadChunkBytes = lambda *args, **kwargs: b"fake"  # type: ignore[method-assign]

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            subtitles = coordinator.TranscribeMedia(media.name)

        self.assertLoggedEqual("line count", 1, subtitles.linecount)
        assert subtitles.originals is not None  # Type narrowing for PyLance
        self.assertLoggedEqual("kept text", "audible", subtitles.originals[0].text)

    def test_no_speech_raises(self):
        """Media with nothing transcribable raises instead of empty project."""
        coordinator, _ = self._coordinator(["", "   "])
        coordinator.chunker.PlanScenes = lambda media_path, track=0: [  # type: ignore[method-assign]
            SceneChunk(start=timedelta(seconds=0), end=timedelta(seconds=2)),
        ]
        coordinator.extractor.ReadChunkBytes = lambda *args, **kwargs: b"fake"  # type: ignore[method-assign]

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            with self.assertRaises(SubtitleError):
                coordinator.TranscribeMedia(media.name)

    def test_segment_callback_receives_each_scene(self):
        """Per-scene callback fires with timings for live progress display."""
        coordinator, _ = self._coordinator(["first line", "second line"])
        coordinator.chunker.PlanScenes = lambda media_path, track=0: [  # type: ignore[method-assign]
            SceneChunk(start=timedelta(seconds=0), end=timedelta(seconds=4)),
            SceneChunk(start=timedelta(seconds=6), end=timedelta(seconds=10)),
        ]
        coordinator.extractor.ReadChunkBytes = lambda *args, **kwargs: b"fake"  # type: ignore[method-assign]

        seen : list = []
        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            coordinator.TranscribeMedia(media.name, segment_cb=seen.append)

        self.assertLoggedEqual("callback count", 2, len(seen))
        self.assertLoggedEqual("first start", timedelta(seconds=0), seen[0].start)
        self.assertLoggedEqual("second text", "second line", seen[1].text)

    def test_engine_words_grouped_into_lines(self):
        """Word timings from the engine produce truly timed lines."""
        words = [_word("first", 0.0, 1.0), _word("line", 1.0, 2.0),
                 _word("second", 5.0, 6.0), _word("line", 6.0, 7.0)]
        coordinator, _ = self._coordinator(["first line second line"], words)
        coordinator.chunker.PlanScenes = lambda media_path, track=0: [  # type: ignore[method-assign]
            SceneChunk(start=timedelta(seconds=10), end=timedelta(seconds=20)),
        ]
        coordinator.extractor.ReadChunkBytes = lambda *args, **kwargs: b"fake"  # type: ignore[method-assign]

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            subtitles = coordinator.TranscribeMedia(media.name)

        self.assertLoggedEqual("line count", 2, subtitles.linecount)
        assert subtitles.originals is not None  # Type narrowing for PyLance
        self.assertLoggedEqual("first start", timedelta(seconds=10), subtitles.originals[0].start)
        self.assertLoggedEqual("second start", timedelta(seconds=15), subtitles.originals[1].start)

    def test_audio_track_info_label(self):
        """Track descriptors render a readable label."""
        info = AudioTrackInfo(index=1, codec="ac3", language="chi")

        self.assertLoggedEqual("label", "Track 1 - ac3 - chi", str(info))


if __name__ == '__main__':
    unittest.main()
