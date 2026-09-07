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
from PySubtrans.SubtitleError import ExcessiveDurationError, SubtitleError
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

class FailingTranscriptionClient(FakeTranscriptionClient):
    """Fake client with scripted backend failures for abort testing."""
    def __init__(self, *args, fail_on : set[int]|None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fail_on : set[int] = set(fail_on or [])

    def _transcribe_chunk(self, audio_bytes : bytes, audio_format : str, language : str|None) -> TranscriptionResult:
        if self.calls + 1 in self.fail_on:
            self.calls += 1
            raise SubtitleError("simulated backend failure")
        return super()._transcribe_chunk(audio_bytes, audio_format, language)

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
def _make_dialogue_wav(path : str, tone_seconds : float = 6.0, pause_seconds : float = 1.0, repeats : int = 12) -> None:
    """Dialogue-like audio: tone bursts separated by digital silence (no ffmpeg needed)."""
    sample_rate = 16000
    tone = array.array('h', (int(10000 * math.sin(2.0 * math.pi * 440.0 * i / sample_rate))
                             for i in range(int(tone_seconds * sample_rate))))
    silence = array.array('h', [0] * int(pause_seconds * sample_rate))
    samples = array.array('h')
    for _unused_repeat in range(repeats):
        samples.extend(tone)
        samples.extend(silence)
    with wave.open(path, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(samples.tobytes())
def stub_media(testcase : LoggedTestCase, coordinator : TranscriptionCoordinator,
               chunks : list[AudioChunk], audio : bytes = b"fake") -> None:
    """
    Stub chunk planning and audio reads for a coordinator test run.

    patch.object restores the real methods afterwards; plain attribute
    assignment would need type: ignore comments and leak stubs on failure.
    """
    chunk_patcher = patch.object(coordinator.chunker, "PlanChunks", return_value=chunks)
    bytes_patcher = patch.object(coordinator.extractor, "ReadChunkBytes", return_value=audio)
    chunk_patcher.start()
    bytes_patcher.start()
    testcase.addCleanup(chunk_patcher.stop)
    testcase.addCleanup(bytes_patcher.stop)
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

    def test_dense_dialogue_respects_minimum(self):
        """Frequent pauses never produce sub-minimum chunks."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wav_path = os.path.join(tmpdir, "dialogue.wav")
            _make_dialogue_wav(wav_path, repeats=24)

            chunker = AudioChunker(SettingsType({'min_chunk_seconds': 8.0, 'max_chunk_seconds': 60.0}))
            chunks = chunker.PlanChunks(wav_path)

        self.assertLoggedGreater("several chunks planned", len(chunks), 2)
        for chunk in chunks:
            self.assertLoggedGreaterEqual(
                "chunk respects minimum",
                (chunk.end - chunk.start).total_seconds(), 8.0)

    def test_raising_maximum_reduces_chunk_count(self):
        """The cap is the lever for fewer, larger chunks on dialogue."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wav_path = os.path.join(tmpdir, "dialogue.wav")
            _make_dialogue_wav(wav_path, repeats=24)

            capped = AudioChunker(SettingsType({'min_chunk_seconds': 8.0, 'max_chunk_seconds': 30.0}))
            capped_chunks = capped.PlanChunks(wav_path)
            roomy = AudioChunker(SettingsType({'min_chunk_seconds': 8.0, 'max_chunk_seconds': 60.0}))
            roomy_chunks = roomy.PlanChunks(wav_path)

        self.assertLoggedGreater("fewer chunks with higher cap", len(capped_chunks), len(roomy_chunks))
        for chunk in roomy_chunks:
            self.assertLoggedGreaterEqual(
                "large chunks respect minimum",
                (chunk.end - chunk.start).total_seconds(), 8.0)

    def test_long_gap_beats_nearer_short_gap(self):
        """A long pause earlier wins over a short one nearer the cap."""
        chunker = AudioChunker(SettingsType({'min_chunk_seconds': 8.0, 'max_chunk_seconds': 60.0}))
        silences = [
            (timedelta(seconds=20), timedelta(seconds=25)),
            (timedelta(seconds=55), timedelta(seconds=56)),
        ]
        cut = chunker._next_silence_cut(silences, 0, timedelta(seconds=0), timedelta(seconds=60))

        assert cut is not None  # Type narrowing for PyLance
        self.assertLoggedEqual("cut at long gap", timedelta(seconds=20), cut[0])

    def test_ties_break_toward_latest(self):
        """Equal scores prefer the later cut, filling toward the cap."""
        chunker = AudioChunker(SettingsType({'min_chunk_seconds': 8.0, 'max_chunk_seconds': 60.0}))
        silences = [
            (timedelta(seconds=10), timedelta(seconds=15)),
            (timedelta(seconds=25), timedelta(seconds=27)),
        ]
        cut = chunker._next_silence_cut(silences, 0, timedelta(seconds=0), timedelta(seconds=60))

        assert cut is not None  # Type narrowing for PyLance
        self.assertLoggedEqual("cut at later gap", timedelta(seconds=25), cut[0])

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

    def test_sliver_across_pause_stays_separate(self):
        """A short interjection after seconds of silence keeps its own line."""
        words = [_word("seat?", 0.0, 1.0), _word("So...", 11.0, 11.3)]
        lines = self._scene_lines(self._coordinator(), "seat? So...", words)

        self.assertLoggedEqual("line count", 2, len(lines))
        self.assertLoggedEqual("first end", timedelta(seconds=101), lines[0].end)
        self.assertLoggedEqual("second start", timedelta(seconds=111), lines[1].start)
        self.assertLoggedEqual("second end", timedelta(seconds=111.3), lines[1].end)
        self.assertLoggedEqual("second text", "So...", lines[1].text)

    def test_sliver_after_short_pause_merges(self):
        """A fragment hard on the heels of the previous line still folds in."""
        words = [_word("yes", 0.0, 1.0, "A"), _word("um", 1.2, 1.4, "B")]
        lines = self._scene_lines(self._coordinator(), "yes um", words)

        self.assertLoggedEqual("line count", 1, len(lines))
        self.assertLoggedEqual("merged span", timedelta(seconds=101.4), lines[0].end)
        self.assertLoggedEqual("merged text", "yes um", lines[0].text)

    def test_leading_sliver_across_pause_stays_separate(self):
        """A leading fragment far from the next line is not pulled forward."""
        words = [_word("oh", 0.0, 0.2), _word("hello", 5.0, 6.0)]
        lines = self._scene_lines(self._coordinator(), "oh hello", words)

        self.assertLoggedEqual("line count", 2, len(lines))
        self.assertLoggedEqual("first text", "oh", lines[0].text)
        self.assertLoggedEqual("second start", timedelta(seconds=105), lines[1].start)

    def test_leading_sliver_after_short_pause_merges(self):
        """A leading fragment close to the next line folds forward."""
        words = [_word("oh.", 0.0, 0.2), _word("hello", 0.4, 1.4)]
        lines = self._scene_lines(self._coordinator(), "oh. hello", words)

        self.assertLoggedEqual("line count", 1, len(lines))
        self.assertLoggedEqual("merged start", timedelta(seconds=100), lines[0].start)
        self.assertLoggedEqual("merged end", timedelta(seconds=101.4), lines[0].end)

class TestOverlongSpans(LoggedTestCase):
    def _coordinator(self):
        provider = FakeTranscriptionProvider()
        return TranscriptionCoordinator(provider, SettingsType({'language': 'Chinese'}))

    def _part_segment(self, part_seconds : float) -> TranscriptionSegment:
        chunk = AudioChunk(start=timedelta(seconds=100), end=timedelta(seconds=160))
        part = TranscriptionSegment(start=timedelta(seconds=0), end=timedelta(seconds=part_seconds),
                                    text="monologue", speaker="0")
        return TranscriptionSegment(start=chunk.start, end=chunk.end, text="monologue",
                                    language="Chinese", parts=[part])

    def test_long_part_flags_warning(self):
        """Untimed engine spans beyond the line cap are flagged, not split."""
        coordinator = self._coordinator()
        lines = coordinator._lines_for_segment(self._part_segment(20.0))

        self.assertLoggedEqual("line count", 1, len(lines))
        self.assertLoggedEqual("span kept", timedelta(seconds=120), lines[0].end)
        self.assertLoggedEqual("flagged", True, coordinator._warn_if_overlong(lines[0]))

    def test_short_part_no_warning(self):
        """Ordinary parts pass without warnings."""
        coordinator = self._coordinator()
        lines = coordinator._lines_for_segment(self._part_segment(3.0))

        self.assertLoggedEqual("line count", 1, len(lines))
        self.assertLoggedEqual("flagged", False, coordinator._warn_if_overlong(lines[0]))

    def test_whole_chunk_fallback_flags_warning(self):
        """A flat-text chunk span is flagged when it runs long."""
        coordinator = self._coordinator()
        segment = TranscriptionSegment(start=timedelta(seconds=100), end=timedelta(seconds=160),
                                       text="monologue", language="Chinese")
        lines = coordinator._lines_for_segment(segment)

        self.assertLoggedEqual("line count", 1, len(lines))
        self.assertLoggedEqual("flagged", True, coordinator._warn_if_overlong(lines[0]))

    def test_timed_line_no_warning(self):
        """Word-timed lines are already capped, so they never flag."""
        coordinator = self._coordinator()
        chunk = AudioChunk(start=timedelta(seconds=100), end=timedelta(seconds=160))
        segment = TranscriptionSegment(start=chunk.start, end=chunk.end, text="hi",
                                       language="Chinese", words=[_word("hi", 0.0, 1.0)])
        lines = coordinator._lines_for_segment(segment)

        self.assertLoggedEqual("line count", 1, len(lines))
        self.assertLoggedEqual("flagged", False, coordinator._warn_if_overlong(lines[0]))

    def test_boundary_not_flagged(self):
        """A line exactly at the cap is fine; only overruns flag."""
        coordinator = self._coordinator()
        line = TranscriptionSegment(start=timedelta(seconds=100), end=timedelta(seconds=108),
                                    text="exactly eight seconds")

        self.assertLoggedEqual("flagged", False, coordinator._warn_if_overlong(line))

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
        stub_media(self, coordinator, [
            AudioChunk(start=timedelta(seconds=0), end=timedelta(seconds=2)),
        ], audio=self._silent_wav())

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
        stub_media(self, coordinator, [
            AudioChunk(start=timedelta(seconds=0), end=timedelta(seconds=4)),
            AudioChunk(start=timedelta(seconds=6), end=timedelta(seconds=10)),
        ])

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
        coordinator, _unused_provider = self._coordinator(["first scene", "second scene"])
        stub_media(self, coordinator, [
            AudioChunk(start=timedelta(seconds=0), end=timedelta(seconds=2)),
            AudioChunk(start=timedelta(seconds=2), end=timedelta(seconds=4)),
        ])

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            subtitles = coordinator.TranscribeMedia(media.name)

        self.assertLoggedEqual("line count", 2, subtitles.linecount)
        assert subtitles.originals is not None  # Type narrowing for PyLance
        self.assertLoggedEqual("second span", timedelta(seconds=4), subtitles.originals[1].end)

    def test_no_speech_raises(self):
        """Media with nothing transcribable raises instead of empty project."""
        coordinator, _unused_provider = self._coordinator(["", "   "])
        stub_media(self, coordinator, [
            AudioChunk(start=timedelta(seconds=0), end=timedelta(seconds=2)),
        ])

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            with self.assertRaises(SubtitleError):
                coordinator.TranscribeMedia(media.name)

    def test_segment_callback_receives_each_scene(self):
        """Per-chunk callback fires with timings for live progress display."""
        coordinator, _unused_provider = self._coordinator(["first line", "second line"], [_word("w", 0.0, 1.0)])
        stub_media(self, coordinator, [
            AudioChunk(start=timedelta(seconds=0), end=timedelta(seconds=4)),
            AudioChunk(start=timedelta(seconds=6), end=timedelta(seconds=10)),
        ])

        seen : list = []
        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            coordinator.TranscribeMedia(media.name, segment_cb=seen.append)

        self.assertLoggedEqual("callback count", 2, len(seen))
        self.assertLoggedEqual("second start", timedelta(seconds=6), seen[1].start)

    def test_progress_reports_chunk_spans(self):
        """Progress callbacks carry chunk spans, not transcribed line spans."""
        coordinator, _unused_provider = self._coordinator(["first line", "second line"], [_word("w", 0.0, 1.0)])
        stub_media(self, coordinator, [
            AudioChunk(start=timedelta(seconds=0), end=timedelta(seconds=4)),
            AudioChunk(start=timedelta(seconds=6), end=timedelta(seconds=10)),
        ])

        seen : list = []
        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            coordinator.TranscribeMedia(media.name, progress_cb=lambda done, total, span: seen.append(span))

        self.assertLoggedEqual("chunk spans", ["0.0s-4.0s", "6.0s-10.0s"], seen)

    def test_engine_words_grouped_into_lines(self):
        """Word timings from the engine produce truly timed lines."""
        words = [_word("first", 0.0, 1.0), _word("line", 1.0, 2.0),
                 _word("second", 5.0, 6.0), _word("line", 6.0, 7.0)]
        coordinator, _unused_provider = self._coordinator(["first line second line"], words)
        stub_media(self, coordinator, [
            AudioChunk(start=timedelta(seconds=10), end=timedelta(seconds=20)),
        ])

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            subtitles = coordinator.TranscribeMedia(media.name)

        self.assertLoggedEqual("line count", 2, subtitles.linecount)
        assert subtitles.originals is not None  # Type narrowing for PyLance
        self.assertLoggedEqual("first start", timedelta(seconds=10), subtitles.originals[0].start)
        self.assertLoggedEqual("second start", timedelta(seconds=15), subtitles.originals[1].start)

    def test_abort_keeps_partial_results(self):
        """Cancelling keeps billed work instead of throwing it away."""
        coordinator, _unused_provider = self._coordinator(["first line", "second line"], [_word("w", 0.0, 1.0)])
        stub_media(self, coordinator, [
            AudioChunk(start=timedelta(seconds=0), end=timedelta(seconds=4)),
            AudioChunk(start=timedelta(seconds=6), end=timedelta(seconds=10)),
        ])

        def abort_after_first(done : int, total : int, span : str) -> None:
            if done >= 1:
                coordinator.Abort()

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            subtitles = coordinator.TranscribeMedia(media.name, progress_cb=abort_after_first)

        self.assertLoggedEqual("partial line count", 1, subtitles.linecount)

    def test_abort_before_anything_raises(self):
        """Cancelling with nothing transcribed still raises, not empty output."""
        coordinator, _unused_provider = self._coordinator(["first line"], [_word("w", 0.0, 1.0)])
        stub_media(self, coordinator, [
            AudioChunk(start=timedelta(seconds=0), end=timedelta(seconds=4)),
        ])
        coordinator.Abort()

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            with self.assertRaises(SubtitleError):
                coordinator.TranscribeMedia(media.name)

    def test_audio_track_info_label(self):
        """Track descriptors render a readable label."""
        info = AudioTrackInfo(index=1, codec="ac3", language="chi")

        self.assertLoggedEqual("label", "Track 1 - ac3 - chi", str(info))

    def _failing_coordinator(self, fail_on : set[int], chunks : int = 4, **settings):
        provider = FakeTranscriptionProvider(SettingsType(), ["ok line"])
        failing = FailingTranscriptionClient(SettingsType(), ["ok line"], fail_on=fail_on)
        client_patcher = patch.object(provider, "GetTranscriptionClient", return_value=failing)
        client_patcher.start()
        self.addCleanup(client_patcher.stop)
        coordinator = TranscriptionCoordinator(provider, SettingsType({'min_chunk_seconds': 1.0, **settings}))
        stub_media(self, coordinator, [
            AudioChunk(start=timedelta(seconds=2 * i), end=timedelta(seconds=2 * i + 2)) for i in range(chunks)
        ])
        return coordinator, failing

    def test_two_initial_failures_abort_run(self):
        """Two failures before anything works aborts instead of grinding chunks."""
        coordinator, failing = self._failing_coordinator({1, 2}, chunks=4)

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            with self.assertRaises(SubtitleError) as raised:
                coordinator.TranscribeMedia(media.name)

        # Note: str() prefers the wrapped error, the message carries ours
        self.assertLoggedIn("blocked message", "consecutive", raised.exception.message)
        self.assertLoggedEqual("stopped early", 2, failing.calls)

    def test_isolated_failures_do_not_abort(self):
        """Successes reset the failure count, so blips don't kill runs."""
        coordinator, failing = self._failing_coordinator({1, 3}, chunks=4)

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            subtitles = coordinator.TranscribeMedia(media.name)

        self.assertLoggedEqual("line count", 2, subtitles.linecount)
        self.assertLoggedEqual("all chunks attempted", 4, failing.calls)

    def test_mid_run_consecutive_failures_abort(self):
        """Three consecutive failures mid-run abort even after successes."""
        coordinator, failing = self._failing_coordinator({2, 3, 4}, chunks=6)

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            with self.assertRaises(SubtitleError) as raised:
                coordinator.TranscribeMedia(media.name)

        self.assertLoggedIn("blocked message", "consecutive", raised.exception.message)
        self.assertLoggedEqual("stopped early", 4, failing.calls)

    def test_custom_consecutive_limit(self):
        """The consecutive-failure budget is tunable per run."""
        coordinator, failing = self._failing_coordinator({2, 3, 4, 5}, chunks=6,
                                                          max_consecutive_failures=5)

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            subtitles = coordinator.TranscribeMedia(media.name)

        self.assertLoggedEqual("line count", 2, subtitles.linecount)
        self.assertLoggedEqual("all chunks attempted", 6, failing.calls)

    def test_project_persistence_follows_options(self):
        """GUI projects are persistent like opened files, so autosave uses the project path."""
        coordinator, _unused_provider = self._coordinator(["first line"], [_word("w", 0.0, 1.0)])
        stub_media(self, coordinator, [
            AudioChunk(start=timedelta(seconds=0), end=timedelta(seconds=4)),
        ])

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            persistent = coordinator.CreateTranscriptionProject(media.name, Options({'project_file': True}))
            transient = coordinator.CreateTranscriptionProject(media.name, None)

        self.assertLoggedEqual("persistent with options", True, persistent.use_project_file)
        self.assertLoggedIn("project file alongside media", ".subtrans", persistent.projectfile or "")
        self.assertLoggedEqual("transient without options", False, transient.use_project_file)

    def _project_batches(self, project):
        assert project.subtitles is not None  # Type narrowing for PyLance
        return [batch for scene in project.subtitles.scenes for batch in scene.batches]

    def test_project_postprocesses_transcription_text(self):
        """User normalizations apply to transcribed lines, timings untouched."""
        coordinator, _unused_provider = self._coordinator(["a — b"])
        stub_media(self, coordinator, [
            AudioChunk(start=timedelta(seconds=0), end=timedelta(seconds=4)),
        ])

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            project = coordinator.CreateTranscriptionProject(
                media.name, Options({'project_file': True, 'convert_wide_dashes': True}))

        assert project.subtitles is not None  # Type narrowing for PyLance
        assert project.subtitles.originals is not None  # Type narrowing for PyLance
        self.assertLoggedEqual("dash normalised", "a - b", project.subtitles.originals[0].text)
        self.assertLoggedEqual("start kept", timedelta(seconds=0), project.subtitles.originals[0].start)
        self.assertLoggedEqual("end kept", timedelta(seconds=4), project.subtitles.originals[0].end)

    def test_project_discards_utterances_emptied_by_postprocessing(self) -> None:
        """Filler removal must not introduce empty source lines into a project."""
        for texts in (["Um.", "Um, hello"], ["Um.", "Um."]):
            with self.subTest(texts=texts):
                coordinator, _unused_provider = self._coordinator(list(texts))
                stub_media(self, coordinator, [
                    AudioChunk(start=timedelta(seconds=0), end=timedelta(seconds=4)),
                    AudioChunk(start=timedelta(seconds=6), end=timedelta(seconds=10)),
                ])

                with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
                    project = coordinator.CreateTranscriptionProject(media.name, Options({
                        'remove_filler_words': True, 'filler_words': ['um'],
                        'postprocess_transcription': True,
                    }))

                assert project.subtitles is not None
                originals = project.subtitles.originals or []
                expected = ["Hello"] if texts[1] == "Um, hello" else []
                self.assertLoggedEqual("nonempty source text", expected, [line.text for line in originals])
                batch_lines = [line for batch in self._project_batches(project) for line in batch.originals]
                self.assertLoggedEqual("batch and flat lines agree", originals, batch_lines)
                if originals:
                    self.assertLoggedEqual("surviving start preserved", timedelta(seconds=6), originals[0].start)
                    self.assertLoggedEqual("surviving end preserved", timedelta(seconds=10), originals[0].end)

    def test_project_preprocesses_like_loaded_files(self):
        """Long flat lines split on duration under the post-process toggle."""
        text = "First sentence here. Second sentence here. Third sentence here. Fourth sentence here."
        coordinator, _unused_provider = self._coordinator([text])
        stub_media(self, coordinator, [
            AudioChunk(start=timedelta(seconds=0), end=timedelta(seconds=60)),
        ])

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            project = coordinator.CreateTranscriptionProject(media.name, Options({
                'project_file': True, 'postprocess_transcription': True, 'max_line_duration': 4.0}))

        assert project.subtitles is not None  # Type narrowing for PyLance
        assert project.subtitles.originals is not None  # Type narrowing for PyLance
        self.assertLoggedGreater("line was split", len(project.subtitles.originals), 1)
        for line in project.subtitles.originals:
            self.assertLoggedLessEqual("split shorter than whole", line.duration.total_seconds(), 60.0)
        self.assertLoggedEqual("span start kept", timedelta(seconds=0), project.subtitles.originals[0].start)
        self.assertLoggedEqual("span end kept", timedelta(seconds=60), project.subtitles.originals[-1].end)

    def test_project_skips_preprocess_when_toggled_off(self):
        """Unchecking post-process keeps long flat lines whole."""
        text = "First sentence here. Second sentence here. Third sentence here. Fourth sentence here."
        coordinator, _unused_provider = self._coordinator([text])
        stub_media(self, coordinator, [
            AudioChunk(start=timedelta(seconds=0), end=timedelta(seconds=60)),
        ])

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            project = coordinator.CreateTranscriptionProject(media.name, Options({
                'project_file': True, 'postprocess_transcription': False}))

        assert project.subtitles is not None  # Type narrowing for PyLance
        assert project.subtitles.originals is not None  # Type narrowing for PyLance
        self.assertLoggedEqual("line count", 1, len(project.subtitles.originals))

    def test_project_flags_batches_for_revalidation(self):
        """Fresh transcription batches carry notes and the revalidation tag."""
        coordinator, _unused_provider = self._coordinator(["monologue"])
        stub_media(self, coordinator, [
            AudioChunk(start=timedelta(seconds=0), end=timedelta(seconds=60)),
        ])

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            project = coordinator.CreateTranscriptionProject(media.name, Options({'project_file': True}))

        batches = self._project_batches(project)
        self.assertLoggedGreater("batches built", len(batches), 0)
        for batch in batches:
            self.assertLoggedEqual("revalidation tagged", True, batch.validate_originals)
        error_types = {type(e) for batch in batches for e in batch.errors}
        self.assertLoggedIn("duration note attached", ExcessiveDurationError, error_types)


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
