import array
import io
import math
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
from datetime import timedelta
from unittest.mock import patch

import PySubtrans
from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Options import Options
from PySubtrans.SettingsType import GuiSettingsType, SettingsType
from PySubtrans.SubtitleBuilder import SubtitleBuilder
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

def _word(text : str, start : float, end : float, speaker : str|None = None) -> WordTiming:
    return WordTiming(text=text, start=timedelta(seconds=start), end=timedelta(seconds=end), speaker=speaker)


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

    def test_speaker_change_splits_lines(self):
        """Speaker turns break subtitle lines and label them."""
        words = [_word("yes", 0.0, 0.5, "A"), _word("no", 0.6, 1.0, "B")]
        lines = self._scene_lines(self._coordinator(), "yes no", words)

        self.assertLoggedEqual("line count", 2, len(lines))
        self.assertLoggedEqual("first speaker", "A", lines[0].speaker)
        self.assertLoggedEqual("second speaker", "B", lines[1].speaker)

class TestSettingsNamespaces(LoggedTestCase):
    def _options(self):
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

        samples = array.array('h', [0] * int(16000 * seconds))
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(samples.tobytes())
        return buffer.getvalue()

    def _tone_wav(self, seconds : float = 1.0) -> bytes:

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


    def test_project_persistence_follows_options(self):
        """GUI projects are persistent like opened files, so autosave uses the project path."""
        coordinator, _ = self._coordinator(["first line"], [_word("w", 0.0, 1.0)])
        coordinator.chunker.PlanChunks = lambda media_path, track=0: [  # type: ignore[method-assign]
            AudioChunk(start=timedelta(seconds=0), end=timedelta(seconds=4)),
        ]
        coordinator.extractor.ReadChunkBytes = lambda *args, **kwargs: b"fake"  # type: ignore[method-assign]

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            persistent = coordinator.CreateTranscriptionProject(media.name, Options({'project_file': True}))
            transient = coordinator.CreateTranscriptionProject(media.name, None)

        self.assertLoggedEqual("persistent with options", True, persistent.use_project_file)
        self.assertLoggedIn("project file alongside media", ".subtrans", persistent.projectfile or "")
        self.assertLoggedEqual("transient without options", False, transient.use_project_file)


class TestTranscriptionRateLimit(LoggedTestCase):
    def test_unlimited_by_default(self):
        """No rate limit means no pacing sleep."""
        client = FakeTranscriptionClient()

        with patch("time.sleep") as mock_sleep:
            result = client.TranscribeChunk(b"fake-audio", "wav", "en")

        self.assertLoggedEqual("transcript", "hello world", result.text)
        self.assertLoggedEqual("no pacing", 0, mock_sleep.call_count)

    def test_requests_paced_to_minimum_duration(self):
        """A 60/min limit paces each request to at least one second."""
        client = FakeTranscriptionClient(SettingsType({'rate_limit': 60.0}))

        with patch("time.sleep") as mock_sleep:
            result = client.TranscribeChunk(b"fake-audio", "wav", "en")

        total_slept = sum(call.args[0] for call in mock_sleep.call_args_list)
        self.assertLoggedEqual("transcript", "hello world", result.text)
        self.assertLoggedGreater("paced duration", total_slept, 0.99)

    def test_zero_disables_pacing(self):
        """An explicit zero limit behaves as unlimited."""
        client = FakeTranscriptionClient(SettingsType({'rate_limit': 0.0}))

        with patch("time.sleep") as mock_sleep:
            client.TranscribeChunk(b"fake-audio", "wav", "en")

        self.assertLoggedEqual("no pacing", 0, mock_sleep.call_count)


class TestTranscriptionSave(LoggedTestCase):
    def _subtitles(self):
        builder = SubtitleBuilder()
        builder.BuildLine(timedelta(seconds=1), timedelta(seconds=2), "hello")
        builder.BuildLine(timedelta(seconds=3), timedelta(seconds=4), "world")
        return builder.Build()

    def test_save_srt(self):
        """Transcribed subtitles write as SRT alongside the media."""
        subtitles = self._subtitles()

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "clip.srt")
            subtitles.SaveOriginal(path)

            with open(path, encoding="utf-8") as f:
                content = f.read()

        self.assertLoggedIn("timing marker", "-->", content)
        self.assertLoggedIn("first line", "hello", content)

    def test_save_ass(self):
        """Transcribed subtitles write as ASS alongside the media."""
        subtitles = self._subtitles()

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "clip.ass")
            subtitles.SaveOriginal(path)

            with open(path, encoding="utf-8") as f:
                content = f.read()

        self.assertLoggedIn("dialogue marker", "Dialogue:", content)
        self.assertLoggedIn("first line", "hello", content)

    def _speaker_subtitles(self):
        builder = SubtitleBuilder()
        builder.BuildLine(timedelta(seconds=1), timedelta(seconds=2), "hello", {'speaker': 'Amina'})
        builder.BuildLine(timedelta(seconds=3), timedelta(seconds=4), "world", {'speaker': 'Boris'})
        return builder.Build()

    def test_ass_preserves_speaker_as_actor(self):
        """Speaker labels land in the ASS Actor field."""
        subtitles = self._speaker_subtitles()

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "clip.ass")
            subtitles.SaveOriginal(path)

            with open(path, encoding="utf-8") as f:
                content = f.read()

        self.assertLoggedIn("first actor", ",Amina,", content)
        self.assertLoggedIn("second actor", ",Boris,", content)

    def test_vtt_preserves_speaker_as_voice(self):
        """Speaker labels land in VTT voice tags."""
        subtitles = self._speaker_subtitles()

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "clip.vtt")
            subtitles.SaveOriginal(path)

            with open(path, encoding="utf-8") as f:
                content = f.read()

        self.assertLoggedIn("first voice", "<v Amina>hello</v>", content)
        self.assertLoggedIn("second voice", "<v Boris>world</v>", content)

    def test_srt_drops_speaker(self):
        """SRT has no speaker field, so labels are dropped without touching text."""
        subtitles = self._speaker_subtitles()

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "clip.srt")
            subtitles.SaveOriginal(path)

            with open(path, encoding="utf-8") as f:
                content = f.read()

        self.assertLoggedNotIn("no speaker leak", "Amina", content)
        self.assertLoggedIn("text intact", "hello", content)

class TestProviderImportCost(LoggedTestCase):
    def test_provider_imports_stay_light(self):
        """Registering providers must not pull heavy optional SDKs."""
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(PySubtrans.__file__)))
        script = (
            "import sys; "
            "from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider; "
            "names = sorted(TranscriptionProvider.get_providers()); "
            "heavy = [m for m in ('torch', 'qwen_asr', 'google', 'google.genai') if m in sys.modules]; "
            "assert not heavy, heavy; "
            "print('light ok: ' + ','.join(names))"
        )
        result = subprocess.run([sys.executable, '-c', script], cwd=repo_root,
                                capture_output=True, text=True, timeout=180)

        self.assertLoggedEqual("light imports", 0, result.returncode,
                               input_value=(result.stderr or "")[-2000:])


if __name__ == '__main__':
    unittest.main()
