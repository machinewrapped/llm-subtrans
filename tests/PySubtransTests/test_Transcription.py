import array
import io
import json
import logging
import math
import os
import tempfile
import unittest
import wave
from datetime import timedelta
from unittest.mock import patch

import httpx

from PySubtrans.Helpers.Speech import EstimateSpeechSeconds, SentenceEnds, SentenceRanges
from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Helpers.Tests import skip_if_debugger_attached
from PySubtrans.Options import Options
from PySubtrans.SettingsType import GuiSettingsType, SettingsType
from PySubtrans.SubtitleBuilder import SubtitleBuilder
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.Subtitles import Subtitles
from PySubtrans.Transcription.AudioChunker import AudioChunk, AudioChunker
from PySubtrans.Transcription.AudioExtractor import AudioExtractor, AudioTrack
from PySubtrans.Transcription.LineMerger import MIN_TIMING_CORRECTION
from PySubtrans.Transcription.LineSettings import LineSettings
from PySubtrans.Transcription.SilenceStream import SilenceStream
from PySubtrans.Transcription.WordTiming import WordTiming
from PySubtrans.Transcription.TranscriptionCapture import LoadCaptureLineSettings
from PySubtrans.Transcription.TranscriptionClient import TranscriptionClient
from PySubtrans.Transcription.TranscriptionCoordinator import TranscriptionCoordinator, TranscriptionStatus
from PySubtrans.Transcription.TranscriptionLines import MIN_WORD_CAP_SECONDS, WORD_CAP_MULTIPLE, TranscriptionLineBuilder
from PySubtrans.Transcription.TranscriptionOutcome import TranscriptionOutcome
from PySubtrans.Transcription.TranscriptionProvider import OptionsScope, TranscriptionProvider
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionResult, TranscriptionSegment
from PySubtrans.Transcription.WordAlignment import WordCoverage

from tests.Helpers import FakeClock


def setUpModule() -> None:
    """Unit fixtures supply media data and do not require FFmpeg executables."""
    availability_patcher = patch('PySubtrans.Transcription.AudioExtractor.CheckFfmpegAvailable')
    availability_patcher.start()
    unittest.addModuleCleanup(availability_patcher.stop)


class FakeTranscriptionClient(TranscriptionClient):
    def __init__(self, settings : SettingsType|None = None, texts : list[str]|None = None,
                 words : list[WordTiming]|None = None, timestamps : bool = True,
                 parts : list[TranscriptionSegment]|None = None):
        super().__init__(settings or SettingsType())
        self.texts : list[str] = texts if texts is not None else ["hello world"]
        self.words : list[WordTiming] = words or []
        self.parts : list[TranscriptionSegment] = parts or []
        self.timed : bool = timestamps
        self.calls : int = 0

    @property
    def supports_timestamps(self) -> bool:
        """Test-controlled capability flag."""
        return self.timed

    def _transcribe_chunk(self, audio_bytes : bytes, audio_format : str) -> TranscriptionResult:
        self.calls += 1
        text = self.texts[(self.calls - 1) % len(self.texts)] if self.texts else ""
        return TranscriptionResult(text=text, language=self.language, words=list(self.words), parts=list(self.parts))

class FailingTranscriptionClient(FakeTranscriptionClient):
    """Fake client with scripted backend failures for abort testing."""
    def __init__(self, *args, fail_on : set[int]|None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fail_on : set[int] = set(fail_on or [])

    def _transcribe_chunk(self, audio_bytes : bytes, audio_format : str) -> TranscriptionResult:
        if self.calls + 1 in self.fail_on:
            self.calls += 1
            raise SubtitleError("simulated backend failure")
        return super()._transcribe_chunk(audio_bytes, audio_format)




def stub_media(testcase : LoggedTestCase, coordinator : TranscriptionCoordinator,
               chunks : list[AudioChunk], audio : bytes = b"fake") -> None:
    """
    Stub chunk planning and audio reads for a coordinator test run.

    patch.object restores the real methods afterwards; plain attribute
    assignment would need type: ignore comments and leak stubs on failure.
    """
    chunk_patcher = patch.object(coordinator.chunker, "PlanChunksStream",
                                 side_effect=lambda *args, **kwargs: (chunk for chunk in chunks))
    bytes_patcher = patch.object(coordinator.extractor, "ReadChunkBytes", return_value=audio)
    chunk_patcher.start()
    bytes_patcher.start()
    testcase.addCleanup(chunk_patcher.stop)
    testcase.addCleanup(bytes_patcher.stop)
class FakeTranscriptionProvider(TranscriptionProvider):
    """In-test transcription provider with canned client responses."""
    name = "Fake Transcription"

    def __init__(self, settings : SettingsType|None = None, texts : list[str]|None = None,
                 words : list[WordTiming]|None = None, timestamps : bool = True,
                 parts : list[TranscriptionSegment]|None = None):
        settings = settings or SettingsType()
        super().__init__(self.name, settings)
        self.settings = SettingsType(self.settings | {
            'api_key': settings.get_str('api_key'),
            'model': settings.get_str('model'),
        })
        self.texts : list[str]|None = texts
        self.words : list[WordTiming]|None = words
        self.parts : list[TranscriptionSegment]|None = parts
        self.timed : bool = timestamps
        self.client : FakeTranscriptionClient|None = None

    def GetAvailableModels(self) -> list[str]:
        """Static model list for tests."""
        return ['fake-model']

    def GetTranscriptionClient(self, settings : SettingsType) -> TranscriptionClient:
        """Client returning the canned responses."""
        self.client = FakeTranscriptionClient(settings, self.texts, self.words, self.timed, self.parts)
        return self.client

    def GetOptions(self, settings : SettingsType, scope : OptionsScope = OptionsScope.ALL) -> GuiSettingsType:
        """Settings schema exercising text and dropdown widgets."""
        options : GuiSettingsType = {
            'model': (self.available_models, "Model to use"),
            'language': (str, "Language hint"),
        }

        if scope is OptionsScope.ALL:
            options.update(self._line_options())

        return options

    information_noapikey = "Test walkthrough"

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

class TestAudioChunker(LoggedTestCase):
    @skip_if_debugger_attached
    def test_rejects_minimum_longer_than_maximum(self):
        """Invalid chunk bounds fail before planning can drop the tail."""
        with self.assertRaises(SubtitleError):
            AudioChunker(SettingsType({'min_chunk_seconds': 60.0, 'max_chunk_seconds': 10.0}))

    def test_duration_callback_reports_total_audio(self):
        """Streaming chunk planning exposes the media duration before the first chunk."""
        chunker = AudioChunker(SettingsType({'min_chunk_seconds': 1.0}))
        durations : list[timedelta] = []

        with patch.object(chunker.extractor, 'GetDuration', return_value=timedelta(seconds=10)), \
             patch.object(chunker.extractor, 'DetectSilencesStream', return_value=iter(())):
            chunks = list(chunker.PlanChunksStream('fake.wav', duration_cb=durations.append))

        self.assertLoggedEqual('reported duration', [timedelta(seconds=10)], durations)
        self.assertLoggedEqual('planned chunk end', timedelta(seconds=10), chunks[0].end)

    def test_plan_chunks_from_media_metadata(self):
        """Chunk planning uses duration and detected silence without media processes."""
        cases = [
            ("middle silence", 10, [(4, 6)], 30, [(0, 4), (6, 10)]),
            ("lookahead", 72, [(65, 67)], 60, [(0, 65), (67, 72)]),
            ("hard cap", 12, [], 5, [(0, 5), (5, 10), (10, 12)]),
        ]
        for label, duration, gaps, maximum, expected in cases:
            with self.subTest(label=label):
                chunker = AudioChunker(SettingsType({
                    'min_chunk_seconds': 2.0, 'max_chunk_seconds': maximum,
                    'lookahead_seconds': 30.0}))
                silences = [(timedelta(seconds=start), timedelta(seconds=end)) for start, end in gaps]
                with patch.object(chunker.extractor, 'GetDuration', return_value=timedelta(seconds=duration)), \
                     patch.object(chunker.extractor, 'DetectSilencesStream', return_value=iter(silences)):
                    chunks = chunker.PlanChunks('fake.wav')
                actual = [(chunk.start.total_seconds(), chunk.end.total_seconds()) for chunk in chunks]
                self.assertLoggedEqual(label, expected, actual)











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



    def test_stream_finalizes_chunks_before_scan_completes(self):
        """Chunks are yielded while the silence scan is still in flight."""
        chunker = AudioChunker(SettingsType({'min_chunk_seconds': 8.0, 'max_chunk_seconds': 60.0}))
        pulled : list[int] = []

        def slow_scan():
            for i, silence in enumerate([
                    (timedelta(seconds=55), timedelta(seconds=60)),
                    (timedelta(seconds=130), timedelta(seconds=140)),
                    (timedelta(seconds=500), timedelta(seconds=510))]):
                pulled.append(i)
                yield silence

        with patch.object(chunker.extractor, "GetDuration", return_value=timedelta(seconds=600)):
            with patch.object(chunker.extractor, "DetectSilencesStream", return_value=slow_scan()):
                stream = chunker.PlanChunksStream("fake.mkv")
                first_chunk = next(stream)
                stream.close()

        self.assertLoggedEqual("first chunk start", timedelta(seconds=0), first_chunk.start)
        self.assertLoggedEqual("first chunk cut", timedelta(seconds=55), first_chunk.end)
        # Only the events inside the first decision window (+1 lookahead
        # probe) may be consumed; the 500s event must remain unpulled
        self.assertLoggedEqual("scan events pulled", 2, len(pulled))


class TestSilenceStream(LoggedTestCase):
    def test_ffmpeg_stderr_uses_tolerant_utf8_decoding(self):
        """Invalid diagnostic bytes do not prevent silence events from being parsed."""
        class FakeProcess:
            def __init__(self):
                self.stderr : io.TextIOBase|None = None

            def poll(self) -> int:
                return 0

            def wait(self, timeout : float|None = None) -> int:
                return 0

        fake_process = FakeProcess()

        def create_process(*command_args : object, **process_kwargs : object) -> FakeProcess:
            encoding = process_kwargs.get('encoding')
            errors = process_kwargs.get('errors')
            assert isinstance(encoding, str)
            assert isinstance(errors, str)
            fake_process.stderr = io.TextIOWrapper(
                io.BytesIO(
                    b"[ffmpeg]\x81 diagnostic bytes\n"
                    b"[silencedetect] silence_start: 1.25\n"
                    b"[silencedetect] silence_end: 2.50\n"),
                encoding=encoding, errors=errors)
            return fake_process

        with tempfile.NamedTemporaryFile(suffix='.mkv') as media:
            with patch('PySubtrans.Transcription.AudioExtractor.subprocess.Popen',
                       side_effect=create_process) as popen:
                with SilenceStream(media.name, ffmpeg_path='custom-ffmpeg') as stream:
                    events = list(stream)

        call_args = popen.call_args
        assert call_args is not None
        process_kwargs = call_args.kwargs
        self.assertLoggedEqual('explicit streaming ffmpeg path', 'custom-ffmpeg', call_args.args[0][0])
        self.assertLoggedEqual('ffmpeg text encoding', 'utf-8', process_kwargs['encoding'])
        self.assertLoggedEqual('ffmpeg decode error handling', 'replace', process_kwargs['errors'])
        self.assertLoggedEqual('silence event count', 1, len(events))
        self.assertLoggedEqual('silence start', timedelta(seconds=1.25), events[0][0])
        self.assertLoggedEqual('silence end', timedelta(seconds=2.5), events[0][1])

def _word(text : str, start : float, end : float, speaker : str|None = None) -> WordTiming:
    return WordTiming(text=text, start=timedelta(seconds=start), end=timedelta(seconds=end), speaker=speaker)


def _subtitles_of(outcome : TranscriptionOutcome) -> Subtitles:
    """Unwrap a run outcome that is expected to carry subtitles."""
    assert outcome.subtitles is not None, f"expected subtitles, got {outcome.status} ({outcome.error})"
    return outcome.subtitles


def _default_builder() -> TranscriptionLineBuilder:
    """Line builder with the coordinator's default limits."""
    return TranscriptionLineBuilder(LineSettings(max_line_chars=120, max_line_seconds=4.0, min_split_chars=3))


def _uniform_words(texts : list[str], seconds_each : float = 1.0, start : float = 0.0) -> list[WordTiming]:
    """Contiguous words of equal duration, so only text and position distinguish boundaries."""
    return [_word(text, start + i * seconds_each, start + (i + 1) * seconds_each) for i, text in enumerate(texts)]


class TestWordGrouping(LoggedTestCase):
    def _builder(self):
        return _default_builder()

    def _scene_lines(self, builder : TranscriptionLineBuilder, text : str, words : list[WordTiming], language : str|None = "Chinese"):
        # A transcript would take precedence over the words, so it is left out to test word grouping
        chunk = AudioChunk(start=timedelta(seconds=100), end=timedelta(seconds=160))
        segment = TranscriptionSegment(start=chunk.start, end=chunk.end, text="" if words else text,
                                       language=language, words=words)
        return builder.LinesForSegment(segment)

    def test_aligned_words_group_into_true_lines(self):
        """Line boundaries and timings come from aligned words."""
        words = [_word("師傅", 0.0, 0.5), _word("來了", 0.5, 1.0),
                 _word("。", 1.0, 1.1), _word("他們", 3.0, 3.5), _word("騎馬", 3.5, 4.0)]
        lines = self._scene_lines(self._builder(), "師傅來了。他們騎馬", words)

        self.assertLoggedEqual("line count", 2, len(lines))
        self.assertLoggedEqual("first start", timedelta(seconds=100), lines[0].start)
        self.assertLoggedEqual("first end", timedelta(seconds=101.1), lines[0].end)
        self.assertLoggedEqual("second start", timedelta(seconds=103), lines[1].start)
        self.assertLoggedEqual("no fabrication", timedelta(seconds=104), lines[1].end)

    def test_limit_measures_the_whole_unordered_span(self):
        """A word timed earlier than the one before it cannot hide how long the line really runs."""
        words = [_word("alpha", 0.0, 0.5), _word("bravo", 0.5, 4.4), _word("charlie", 0.2, 0.4)]
        lines = self._scene_lines(self._builder(), "alpha bravo charlie", words)

        longest = max((line.end - line.start).total_seconds() for line in lines)
        self.assertLoggedLessEqual("longest line within the limit", longest, 4.0)

    def test_runaway_word_is_capped_by_its_length(self):
        """A word stamped across most of the chunk lasts no longer than a generous multiple of its speaking time."""
        words = [_word("嗨", 0.1, 50.0), _word("你好", 55.0, 56.0)]
        lines = self._scene_lines(self._builder(), "嗨你好", words)

        self.assertLoggedEqual("line count", 2, len(lines))
        expected = min(4.0, max(MIN_WORD_CAP_SECONDS, WORD_CAP_MULTIPLE * EstimateSpeechSeconds("嗨")))
        self.assertLoggedEqual("capped end", timedelta(seconds=100.1 + expected), lines[0].end)

    def test_transcript_without_words_is_placed_by_length(self):
        """Sentences with no word timings share the chunk span by characters, each within the line limit."""
        with self.assertLogs(level=logging.INFO):
            lines = self._scene_lines(self._builder(), "你好。我们走吧。", [])

        self.assertLoggedEqual("line count", 2, len(lines))
        self.assertLoggedEqual("first starts with the chunk", timedelta(seconds=100), lines[0].start)
        self.assertLoggedEqual("second starts at its share", timedelta(seconds=100 + 60 * 3 / 8), lines[1].start)
        for line in lines:
            self.assertLoggedLessEqual("within the line limit", (line.end - line.start).total_seconds(), 4.0)

    def test_latin_words_spaced(self):
        """Latin words join with spaces, CJK without."""
        words = [_word("Hello", 0.0, 0.5), _word("world", 0.6, 1.0)]
        builder = self._builder()
        lines = self._scene_lines(builder, "Hello world", words, language="English")

        self.assertLoggedEqual("line count", 1, len(lines))
        self.assertLoggedEqual("spaced text", "Hello world", lines[0].text)

    def test_unicode_words_and_punctuation_are_joined(self):
        """Unicode words receive spaces while punctuation stays attached."""
        words = [_word("café", 0.0, 0.2), _word("noir", 0.2, 0.4),
                 _word(".", 0.4, 0.5), _word("следующий", 0.5, 0.7)]
        lines = self._scene_lines(self._builder(), "café noir. следующий", words)

        self.assertLoggedEqual("unicode spacing", "café noir. следующий", lines[0].text)

    def test_speaker_change_splits_lines(self):
        """Speaker turns break subtitle lines and label them."""
        words = [_word("yes", 0.0, 1.0, "A"), _word("no", 1.1, 2.1, "B")]
        lines = self._scene_lines(self._builder(), "yes no", words)

        self.assertLoggedEqual("line count", 2, len(lines))
        self.assertLoggedEqual("first speaker", "A", lines[0].speaker)
        self.assertLoggedEqual("second speaker", "B", lines[1].speaker)

    def test_brief_speaker_turns_combine_into_dialogue(self):
        """Two turns too short to read on their own share a line rather than flicker past."""
        words = [_word("yes", 0.0, 0.5, "A"), _word("no", 0.6, 1.0, "B")]
        lines = self._scene_lines(self._builder(), "yes no", words)

        self.assertLoggedEqual("line count", 1, len(lines))
        self.assertLoggedEqual("dialogue text", "- yes\n- no", lines[0].text)
        self.assertLoggedEqual("mixed speaker attribution", None, lines[0].speaker)

    def test_same_speaker_continues_across_moderate_pause(self):
        """One speaker pausing mid-clause keeps a single line instead of two fragments."""
        words = [_word("以为自己", 0.0, 0.559, "0"), _word("是只鬼。", 1.28, 2.08, "0")]
        lines = self._scene_lines(self._builder(), "以为自己是只鬼。", words)

        self.assertLoggedEqual("line count", 1, len(lines))
        self.assertLoggedEqual("merged text", "以为自己是只鬼。", lines[0].text)
        self.assertLoggedEqual("merged start", timedelta(seconds=100), lines[0].start)
        self.assertLoggedEqual("merged end", timedelta(seconds=102.08), lines[0].end)

    def test_unknown_speaker_keeps_tighter_pause_limit(self):
        """Without speaker information the same pause is treated as a real break."""
        words = [_word("以为自己", 0.0, 0.559), _word("是只鬼。", 1.28, 2.08)]
        lines = self._scene_lines(self._builder(), "以为自己是只鬼。", words)

        self.assertLoggedEqual("line count", 2, len(lines))

    def test_speaker_turns_stay_separate_when_merging_is_disabled(self):
        """The same brief turns that normally share a line keep their own when turn merging is off."""
        builder = TranscriptionLineBuilder(LineSettings(max_line_chars=120, max_line_seconds=4.0, min_split_chars=3,
                                                        can_merge_different_speakers=False))
        words = [_word("yes", 0.0, 0.5, "A"), _word("no", 0.6, 1.0, "B")]
        lines = self._scene_lines(builder, "yes no", words)

        self.assertLoggedEqual("line count", 2, len(lines))
        self.assertLoggedEqual("first speaker", "A", lines[0].speaker)
        self.assertLoggedEqual("second speaker", "B", lines[1].speaker)

    def test_one_speaker_still_merges_when_turn_merging_is_disabled(self):
        """Disabling turn merging bears on speaker changes only, not on one speaker's fragments."""
        builder = TranscriptionLineBuilder(LineSettings(max_line_chars=120, max_line_seconds=4.0, min_split_chars=3,
                                                        can_merge_different_speakers=False))
        words = [_word("以为自己", 0.0, 0.559, "0"), _word("是只鬼。", 1.28, 2.08, "0")]
        lines = self._scene_lines(builder, "以为自己是只鬼。", words)

        self.assertLoggedEqual("line count", 1, len(lines))
        self.assertLoggedEqual("merged text", "以为自己是只鬼。", lines[0].text)

    def test_configured_gaps_override_the_defaults(self):
        """A pause past the default limit still joins when the settings allow it."""
        words = [_word("以为自己", 0.0, 0.559, "0"), _word("是只鬼。", 1.9, 2.7, "0")]

        default_lines = self._scene_lines(self._builder(), "以为自己是只鬼。", words)
        self.assertLoggedEqual("line count with default gaps", 2, len(default_lines))

        generous = TranscriptionLineBuilder(LineSettings(max_line_chars=120, max_line_seconds=4.0, min_split_chars=3,
                                                         same_speaker_merge_eligible_gap=2.0))
        lines = self._scene_lines(generous, "以为自己是只鬼。", words)
        self.assertLoggedEqual("line count with a wider same-speaker gap", 1, len(lines))

    def test_sliver_across_pause_stays_separate(self):
        """A short interjection after seconds of silence keeps its own line, extended to the minimum duration."""
        words = [_word("seat?", 0.0, 1.0), _word("So...", 11.0, 11.3)]
        lines = self._scene_lines(self._builder(), "seat? So...", words)

        self.assertLoggedEqual("line count", 2, len(lines))
        self.assertLoggedEqual("first end", timedelta(seconds=101), lines[0].end)
        self.assertLoggedEqual("second start", timedelta(seconds=111), lines[1].start)
        self.assertLoggedEqual("second end", timedelta(seconds=111.8), lines[1].end)
        self.assertLoggedEqual("second text", "So...", lines[1].text)

    def test_readable_line_does_not_absorb_a_trailing_fragment(self):
        """A line already long enough to read keeps to itself, however close the next fragment."""
        words = [_word("yes", 0.0, 1.0, "A"), _word("um", 1.2, 1.4, "B")]
        lines = self._scene_lines(self._builder(), "yes um", words)

        self.assertLoggedEqual("line count", 2, len(lines))
        self.assertLoggedEqual("readable line kept its own span", timedelta(seconds=101), lines[0].end)
        self.assertLoggedEqual("fragment text", "um", lines[1].text)

    def test_stranded_fragment_takes_the_line_behind_it(self):
        """A fragment a full line will not host adopts its follower instead of standing alone."""
        words = [_word("yes", 0.0, 1.0, "A"), _word("um", 1.2, 1.4, "B"),
                 _word("indeed", 1.5, 2.6, "B")]
        lines = self._scene_lines(self._builder(), "yes um indeed", words)

        self.assertLoggedEqual("line count", 2, len(lines))
        self.assertLoggedEqual("readable line kept its own span", timedelta(seconds=101), lines[0].end)
        self.assertLoggedEqual("fragment joined its follower", "um indeed", lines[1].text)

    def test_three_speaker_slivers_keep_all_dialogue_turns(self):
        """Merging a third speaker keeps earlier dialogue markers and attribution."""
        words = [_word("I", 0.0, 0.1, "A"), _word("say!", 0.1, 0.2, "A"),
                 _word("Of", 0.25, 0.35, "B"), _word("course!", 0.35, 0.45, "B"),
                 _word("Indeed!", 0.5, 0.6, "C")]
        lines = self._scene_lines(self._builder(), "I say! Of course! Indeed!", words)

        self.assertLoggedEqual("three turn count", 1, len(lines))
        self.assertLoggedEqual("three turn text", "- I say!\n- Of course!\n- Indeed!", lines[0].text)
        self.assertLoggedEqual("mixed speaker attribution", None, lines[0].speaker)

    def test_leading_sliver_across_pause_stays_separate(self):
        """A leading fragment far from the next line is not pulled forward."""
        words = [_word("oh", 0.0, 0.2), _word("hello", 5.0, 6.0)]
        lines = self._scene_lines(self._builder(), "oh hello", words)

        self.assertLoggedEqual("line count", 2, len(lines))
        self.assertLoggedEqual("first text", "oh", lines[0].text)
        self.assertLoggedEqual("second start", timedelta(seconds=105), lines[1].start)

    def test_leading_sliver_after_short_pause_merges(self):
        """A leading fragment close to the next line folds forward."""
        words = [_word("oh.", 0.0, 0.2), _word("hello", 0.4, 1.4)]
        lines = self._scene_lines(self._builder(), "oh. hello", words)

        self.assertLoggedEqual("line count", 1, len(lines))
        self.assertLoggedEqual("merged start", timedelta(seconds=100), lines[0].start)
        self.assertLoggedEqual("merged end", timedelta(seconds=101.4), lines[0].end)


class TestSliverMergeLimits(LoggedTestCase):
    """A run of fragments divides into readable pieces instead of one dense block."""

    def _turns(self, texts : list[str], speakers : list[str]) -> list[TranscriptionSegment]:
        """Half-second turns a fifth of a second apart, so every one is a fragment."""
        lines : list[TranscriptionSegment] = []
        for index, (text, speaker) in enumerate(zip(texts, speakers)):
            start = index * 0.7
            lines.append(TranscriptionSegment(start=timedelta(seconds=start),
                                              end=timedelta(seconds=start + 0.5),
                                              text=text, speaker=speaker))
        return lines

    def test_four_turns_divide_into_pairs(self):
        """Four turns make a pair of pairs rather than three turns and an orphan."""
        lines = self._turns(["够了。", "蛤？", "够了？", "不适了？"], ["0", "1", "0", "1"])
        merged = _default_builder().merger.MergeSlivers(lines)

        self.assertLoggedEqual("line count", 2, len(merged))
        self.assertLoggedEqual("first pair", "- 够了。\n- 蛤？", merged[0].text)
        self.assertLoggedEqual("second pair", "- 够了？\n- 不适了？", merged[1].text)

    def test_five_turns_respect_the_newline_limit(self):
        """A five turn scramble divides rather than stacking onto one subtitle."""
        lines = self._turns(["我死我死", "早生啊！", "我死", "打你啊！", "點樣啊？"],
                            ["0", "1", "0", "1", "0"])
        merged = _default_builder().merger.MergeSlivers(lines)

        self.assertLoggedEqual("line count", 2, len(merged))
        self.assertLoggedEqual("first piece", "- 我死我死\n- 早生啊！\n- 我死", merged[0].text)
        self.assertLoggedEqual("second piece", "- 打你啊！\n- 點樣啊？", merged[1].text)

    def test_a_turn_arriving_in_fragments_stays_one_turn(self):
        """A speaker resuming after an interruption is one turn, not two dialogue lines."""
        lines = self._turns(["够了。", "蛤？", "不适了？"], ["0", "1", "1"])
        merged = _default_builder().merger.MergeSlivers(lines)

        self.assertLoggedEqual("line count", 1, len(merged))
        self.assertLoggedEqual("two turns, not three", "- 够了。\n- 蛤？不适了？", merged[0].text)
        self.assertLoggedEqual("mixed speaker attribution", None, merged[0].speaker)

    def test_one_speaker_fragments_join_as_continuous_text(self):
        """One speaker's broken up sentence carries no turn markers to limit."""
        lines = self._turns(["我", "不", "知", "道", "啊"], ["0"] * 5)
        merged = _default_builder().merger.MergeSlivers(lines)

        self.assertLoggedEqual("line count", 1, len(merged))
        self.assertLoggedEqual("continuous text", "我不知道啊", merged[0].text)


class TestOverlongUtteranceSplitting(LoggedTestCase):
    """Utterances over a limit split at their best pause instead of stranding a tail."""
    WORDS = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel"]

    def _lines(self, builder : TranscriptionLineBuilder, words : list[WordTiming]):
        chunk = AudioChunk(start=timedelta(seconds=100), end=timedelta(seconds=160))
        # Without a transcript, so the words are grouped directly
        segment = TranscriptionSegment(start=chunk.start, end=chunk.end, language="English", words=words)
        return builder.LinesForSegment(segment)

    def test_uniform_timings_split_at_centre(self):
        """With no pauses or punctuation the most central boundary wins, and timings come from the words."""
        builder = TranscriptionLineBuilder(LineSettings(max_line_chars=200, max_line_seconds=4.0))
        lines = self._lines(builder, _uniform_words(self.WORDS))

        self.assertLoggedEqual("line count", 2, len(lines))
        self.assertLoggedEqual("first text", "alpha bravo charlie delta", lines[0].text)
        self.assertLoggedEqual("second text", "echo foxtrot golf hotel", lines[1].text)
        self.assertLoggedEqual("first span", (timedelta(seconds=100), timedelta(seconds=104)), (lines[0].start, lines[0].end))
        self.assertLoggedEqual("second span", (timedelta(seconds=104), timedelta(seconds=108)), (lines[1].start, lines[1].end))

    def test_limit_never_strands_a_short_tail(self):
        """A sentence just over the character limit splits in the middle, not before its last word."""
        builder = TranscriptionLineBuilder(LineSettings(max_line_chars=40, max_line_seconds=10.0))
        lines = self._lines(builder, _uniform_words(self.WORDS, seconds_each=0.5))

        self.assertLoggedEqual("line count", 2, len(lines))
        self.assertLoggedEqual("first text", "alpha bravo charlie delta", lines[0].text)
        self.assertLoggedEqual("second text", "echo foxtrot golf hotel", lines[1].text)

    def test_longer_pause_off_centre_wins(self):
        """A real pause beats a zero-gap boundary at the exact midpoint."""
        words = _uniform_words(self.WORDS[:6]) + [_word("golf", 6.3, 7.3), _word("hotel", 7.3, 8.3)]
        builder = TranscriptionLineBuilder(LineSettings(max_line_chars=200, max_line_seconds=7.0))
        lines = self._lines(builder, words)

        self.assertLoggedEqual("line count", 2, len(lines))
        self.assertLoggedEqual("first text", "alpha bravo charlie delta echo foxtrot", lines[0].text)
        self.assertLoggedEqual("second text", "golf hotel", lines[1].text)
        self.assertLoggedEqual("second start", timedelta(seconds=106.3), lines[1].start)

    def test_edge_pause_loses_to_central_pause(self):
        """A long pause at the very edge loses to a moderate pause near the middle."""
        words = [_word("alpha", 0.0, 1.0), _word("bravo", 1.45, 2.45), _word("charlie", 2.45, 3.45),
                 _word("delta", 3.45, 4.45), _word("echo", 4.65, 5.65), _word("foxtrot", 5.65, 6.65),
                 _word("golf", 6.65, 7.65), _word("hotel", 7.65, 8.65)]
        builder = TranscriptionLineBuilder(LineSettings(max_line_chars=200, max_line_seconds=7.0))
        lines = self._lines(builder, words)

        self.assertLoggedEqual("line count", 2, len(lines))
        self.assertLoggedEqual("first text", "alpha bravo charlie delta", lines[0].text)
        self.assertLoggedEqual("second text", "echo foxtrot golf hotel", lines[1].text)

    def test_clause_punctuation_preferred(self):
        """A comma boundary wins over a plain boundary nearer the centre."""
        texts = ["alpha", "bravo", "charlie,", "delta", "echo", "foxtrot", "golf", "hotel"]
        builder = TranscriptionLineBuilder(LineSettings(max_line_chars=200, max_line_seconds=5.0))
        lines = self._lines(builder, _uniform_words(texts))

        self.assertLoggedEqual("line count", 2, len(lines))
        self.assertLoggedEqual("first text", "alpha bravo charlie,", lines[0].text)
        self.assertLoggedEqual("second text", "delta echo foxtrot golf hotel", lines[1].text)

    def test_short_word_boundary_avoided(self):
        """The split moves off a short conjunction onto a neighbouring longer word."""
        texts = ["alpha", "bravo", "charlie", "og", "echo", "foxtrot", "golf", "hotel"]
        builder = TranscriptionLineBuilder(LineSettings(max_line_chars=200, max_line_seconds=5.0))
        lines = self._lines(builder, _uniform_words(texts))

        self.assertLoggedEqual("line count", 2, len(lines))
        self.assertLoggedEqual("first text", "alpha bravo charlie", lines[0].text)
        self.assertLoggedEqual("second text", "og echo foxtrot golf hotel", lines[1].text)

    def test_recursive_split_keeps_every_piece_within_limit(self):
        """An utterance more than twice the cap splits repeatedly with no single-word pieces."""
        texts = self.WORDS + ["india"]
        builder = TranscriptionLineBuilder(LineSettings(max_line_chars=200, max_line_seconds=4.0))
        lines = self._lines(builder, _uniform_words(texts))

        self.assertLoggedEqual("line count", 3, len(lines))
        self.assertLoggedEqual("all text kept", " ".join(texts), " ".join(line.text for line in lines))
        for line in lines:
            self.assertLoggedLessEqual("piece duration", (line.end - line.start).total_seconds(), 4.0)
            self.assertLoggedGreater("piece words", len(line.text.split()), 1)

    def test_character_cap_alone_splits_at_centre(self):
        """The character limit triggers the same balanced split as the duration limit."""
        builder = TranscriptionLineBuilder(LineSettings(max_line_chars=20, max_line_seconds=10.0))
        lines = self._lines(builder, _uniform_words(["alpha", "bravo", "charlie", "delta"], seconds_each=0.5))

        self.assertLoggedEqual("line count", 2, len(lines))
        self.assertLoggedEqual("first text", "alpha bravo", lines[0].text)
        self.assertLoggedEqual("second text", "charlie delta", lines[1].text)

    def test_min_split_chars_rejects_short_fragments(self):
        """A boundary that would leave a fragment under min_split_chars is skipped."""
        words = [_word("hello", 0.0, 0.5), _word("big", 0.5, 0.8), _word("wide", 0.8, 2.0), _word("world", 2.0, 3.4)]

        loose = self._lines(TranscriptionLineBuilder(LineSettings(max_line_chars=200, max_line_seconds=3.0, min_split_chars=3)), words)
        self.assertLoggedEqual("loose first text", "hello big wide", loose[0].text)

        strict = self._lines(TranscriptionLineBuilder(LineSettings(max_line_chars=200, max_line_seconds=3.0, min_split_chars=8)), words)
        self.assertLoggedEqual("strict line count", 2, len(strict))
        self.assertLoggedEqual("strict first text", "hello big", strict[0].text)
        self.assertLoggedEqual("strict second text", "wide world", strict[1].text)

    def test_hard_boundaries_precede_limit_splitting(self):
        """Sentence ends and pauses cut first; only the over-long remainder is balanced."""
        texts = ["one!", "alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel"]
        builder = TranscriptionLineBuilder(LineSettings(max_line_chars=200, max_line_seconds=4.0))
        lines = self._lines(builder, _uniform_words(texts))

        self.assertLoggedEqual("line count", 3, len(lines))
        self.assertLoggedEqual("sentence text", "one!", lines[0].text)
        self.assertLoggedEqual("first half", "alpha bravo charlie delta", lines[1].text)
        self.assertLoggedEqual("second half", "echo foxtrot golf hotel", lines[2].text)


class TestOverlongSpans(LoggedTestCase):
    def _builder(self):
        return _default_builder()

    def _part_segment(self, part_seconds : float) -> TranscriptionSegment:
        chunk = AudioChunk(start=timedelta(seconds=100), end=timedelta(seconds=160))
        part = TranscriptionSegment(start=timedelta(seconds=0), end=timedelta(seconds=part_seconds),
                                    text="monologue", speaker="0")
        return TranscriptionSegment(start=chunk.start, end=chunk.end, text="monologue",
                                    language="Chinese", parts=[part])

    def test_long_part_flags_warning(self):
        """Untimed engine spans beyond the line cap are flagged, not split."""
        builder = self._builder()
        with self.assertLogs(level=logging.WARNING):
            lines = builder.LinesForSegment(self._part_segment(20.0))
            flagged = builder.WarnIfOverlong(lines[0])

        self.assertLoggedEqual("line count", 1, len(lines))
        self.assertLoggedEqual("span kept", timedelta(seconds=120), lines[0].end)
        self.assertLoggedEqual("flagged", True, flagged)

    def test_short_part_no_warning(self):
        """Ordinary parts pass without warnings."""
        builder = self._builder()
        lines = builder.LinesForSegment(self._part_segment(3.0))

        self.assertLoggedEqual("line count", 1, len(lines))
        self.assertLoggedEqual("flagged", False, builder.WarnIfOverlong(lines[0]))

    def test_same_speaker_part_fragments_merge(self):
        """Fragments the provider segmented for us are still reunited when one speaker owns both."""
        chunk = AudioChunk(start=timedelta(seconds=100), end=timedelta(seconds=160))
        parts = [TranscriptionSegment(start=timedelta(seconds=0), end=timedelta(seconds=0.559),
                                      text="以为自己", speaker="0"),
                 TranscriptionSegment(start=timedelta(seconds=1.28), end=timedelta(seconds=2.08),
                                      text="是只鬼。", speaker="0")]
        segment = TranscriptionSegment(start=chunk.start, end=chunk.end, text="以为自己是只鬼。",
                                       language="Chinese", parts=parts)
        lines = self._builder().LinesForSegment(segment)

        self.assertLoggedEqual("line count", 1, len(lines))
        self.assertLoggedEqual("merged text", "以为自己是只鬼。", lines[0].text)
        self.assertLoggedEqual("merged end", timedelta(seconds=102.08), lines[0].end)

    def test_continuation_after_a_turn_keeps_the_same_speaker_gap(self):
        """A run holding two speakers still judges the next line against the turn it follows."""
        chunk = AudioChunk(start=timedelta(seconds=100), end=timedelta(seconds=160))
        parts = [TranscriptionSegment(start=timedelta(seconds=0), end=timedelta(seconds=0.5),
                                      text="够了", speaker="A"),
                 TranscriptionSegment(start=timedelta(seconds=0.6), end=timedelta(seconds=1.0),
                                      text="蛤", speaker="B"),
                 # 0.7s after B's own turn: too long for a speaker change, not for a continuation
                 TranscriptionSegment(start=timedelta(seconds=1.7), end=timedelta(seconds=2.1),
                                      text="不适了", speaker="B")]
        segment = TranscriptionSegment(start=chunk.start, end=chunk.end, text="够了蛤不适了",
                                       language="Chinese", parts=parts)
        lines = self._builder().LinesForSegment(segment)

        self.assertLoggedEqual("line count", 1, len(lines))
        self.assertLoggedEqual("one turn per speaker", "- 够了\n- 蛤不适了", lines[0].text)

    def test_one_speaker_repeating_costs_no_extra_newline(self):
        """Consecutive fragments from one speaker join as text, so only the turn change breaks a line."""
        builder = TranscriptionLineBuilder(LineSettings(max_line_chars=120, max_line_seconds=4.0, min_split_chars=3,
                                                        max_newlines=1))
        chunk = AudioChunk(start=timedelta(seconds=100), end=timedelta(seconds=160))
        parts = [TranscriptionSegment(start=timedelta(seconds=0), end=timedelta(seconds=0.4),
                                      text="够了", speaker="A"),
                 TranscriptionSegment(start=timedelta(seconds=0.5), end=timedelta(seconds=0.9),
                                      text="真的", speaker="A"),
                 TranscriptionSegment(start=timedelta(seconds=1.0), end=timedelta(seconds=1.4),
                                      text="蛤", speaker="B")]
        segment = TranscriptionSegment(start=chunk.start, end=chunk.end, text="够了真的蛤",
                                       language="Chinese", parts=parts)
        lines = builder.LinesForSegment(segment)

        self.assertLoggedEqual("line count", 1, len(lines))
        self.assertLoggedEqual("one turn break only", "- 够了真的\n- 蛤", lines[0].text)

    def test_distinct_speaker_parts_keep_tighter_pause_limit(self):
        """The same pause that joins one speaker's fragments is a real break between two."""
        chunk = AudioChunk(start=timedelta(seconds=100), end=timedelta(seconds=160))
        parts = [TranscriptionSegment(start=timedelta(seconds=0), end=timedelta(seconds=0.559),
                                      text="你是谁", speaker="0"),
                 TranscriptionSegment(start=timedelta(seconds=1.28), end=timedelta(seconds=2.08),
                                      text="我是警察", speaker="1")]
        segment = TranscriptionSegment(start=chunk.start, end=chunk.end, text="你是谁我是警察",
                                       language="Chinese", parts=parts)
        lines = self._builder().LinesForSegment(segment)

        self.assertLoggedEqual("line count", 2, len(lines))

    def test_untimed_chunk_is_not_one_long_line(self):
        """A transcript with no timings is held to the line limit rather than spread over the whole chunk."""
        builder = self._builder()
        segment = TranscriptionSegment(start=timedelta(seconds=100), end=timedelta(seconds=160),
                                       text="monologue", language="Chinese")
        with self.assertLogs(level=logging.INFO):
            lines = builder.LinesForSegment(segment)

        self.assertLoggedEqual("line count", 1, len(lines))
        self.assertLoggedEqual("duration", timedelta(seconds=4), lines[0].end - lines[0].start)

    def test_long_untimed_transcript_is_left_for_splitting(self):
        """A long transcript with no timings keeps the time it takes to say, so post-processing can split it by duration."""
        builder = self._builder()
        text = " ".join(["word"] * 60)
        segment = TranscriptionSegment(start=timedelta(seconds=100), end=timedelta(seconds=160),
                                       text=text, language="English")
        with self.assertLogs(level=logging.INFO):
            lines = builder.LinesForSegment(segment)

        self.assertLoggedEqual("line count", 1, len(lines))
        self.assertLoggedEqual("duration", timedelta(seconds=EstimateSpeechSeconds(text)), lines[0].end - lines[0].start)
        self.assertLoggedGreater("longer than one line", (lines[0].end - lines[0].start).total_seconds(),
                                 builder.settings.max_line_seconds)

    def test_timed_line_no_warning(self):
        """Word-timed lines are already capped, so they never flag."""
        builder = self._builder()
        chunk = AudioChunk(start=timedelta(seconds=100), end=timedelta(seconds=160))
        segment = TranscriptionSegment(start=chunk.start, end=chunk.end, text="hi",
                                       language="Chinese", words=[_word("hi", 0.0, 1.0)])
        lines = builder.LinesForSegment(segment)

        self.assertLoggedEqual("line count", 1, len(lines))
        self.assertLoggedEqual("flagged", False, builder.WarnIfOverlong(lines[0]))

    def test_boundary_not_flagged(self):
        """A line exactly at the cap is fine; only overruns flag."""
        builder = self._builder()
        line = TranscriptionSegment(start=timedelta(seconds=100), end=timedelta(seconds=104),
                                    text="exactly four seconds")

        self.assertLoggedEqual("flagged", False, builder.WarnIfOverlong(line))


def _part(text : str, start : float, end : float, speaker : str|None = None) -> TranscriptionSegment:
    return TranscriptionSegment(start=timedelta(seconds=start), end=timedelta(seconds=end), text=text, speaker=speaker)


class TestPartsFirst(LoggedTestCase):
    def _lines(self, parts : list[TranscriptionSegment], words : list[WordTiming],
               builder : TranscriptionLineBuilder|None = None) -> list[TranscriptionSegment]:
        segment = TranscriptionSegment(start=timedelta(seconds=100), end=timedelta(seconds=160),
                                       text=''.join(part.text for part in parts), language="Chinese",
                                       parts=parts, words=words)
        return (builder or _default_builder()).LinesForSegment(segment)

    def test_parts_are_preferred_over_words(self):
        """The provider's own segmentation stands, though the words alone would split it at the pause."""
        parts = [_part("以为自己是只鬼。", 0.0, 2.0)]
        words = [_word("以为自己", 0.0, 0.5), _word("是只鬼。", 1.5, 2.0)]
        lines = self._lines(parts, words)

        self.assertLoggedEqual("line count", 1, len(lines))
        self.assertLoggedEqual("part text", "以为自己是只鬼。", lines[0].text)

    def test_long_part_splits_at_its_words(self):
        """A part over the duration limit is cut where its words say, keeping the part's text."""
        parts = [_part("你好，朋友。我们走吧！", 0.0, 8.0, "0")]
        words = _uniform_words(["你好", "，", "朋友", "。", "我们", "走吧", "！"], seconds_each=6.0 / 7)
        lines = self._lines(parts, words)

        self.assertLoggedEqual("line count", 2, len(lines))
        self.assertLoggedEqual("first piece", "你好，朋友。", lines[0].text)
        self.assertLoggedEqual("second piece", "我们走吧！", lines[1].text)
        self.assertLoggedEqual("second starts at its first word", words[4].start + timedelta(seconds=100), lines[1].start)
        self.assertLoggedEqual("speaker kept", "0", lines[1].speaker)

    def test_split_keeps_the_part_spacing(self):
        """Pieces are cut from the part's text, not rebuilt from the words."""
        parts = [_part("Alpha bravo, charlie delta.", 0.0, 8.0)]
        words = _uniform_words(["Alpha", "bravo", ",", "charlie", "delta", "."], seconds_each=8.0 / 6)
        lines = self._lines(parts, words)

        self.assertLoggedEqual("line count", 2, len(lines))
        self.assertLoggedEqual("first piece", "Alpha bravo,", lines[0].text)
        self.assertLoggedEqual("second piece", "charlie delta.", lines[1].text)

    def test_broken_span_takes_its_words_span(self):
        """A part that runs far past its speech is pulled in to where its words are."""
        parts = [_part("要不要跳进去？", 0.0, 19.0)]
        words = [_word("要不要", 1.0, 1.8), _word("跳进去", 1.8, 2.5), _word("？", 2.5, 2.5)]
        lines = self._lines(parts, words)

        self.assertLoggedEqual("line count", 1, len(lines))
        self.assertLoggedEqual("text kept", "要不要跳进去？", lines[0].text)
        self.assertLoggedEqual("start", timedelta(seconds=101.0), lines[0].start)
        self.assertLoggedEqual("end", timedelta(seconds=102.5), lines[0].end)

    def test_split_never_strands_punctuation(self):
        """Utterances separated by a long silence split apart, each keeping its own punctuation."""
        parts = [_part("速。杀了！", 0.0, 30.36)]
        words = [_word("速", 0.0, 0.08), _word("。", 6.66, 6.68), _word("杀", 29.72, 29.8),
                 _word("了", 29.92, 30.0), _word("！", 30.28, 30.36)]
        lines = self._lines(parts, words)

        self.assertLoggedEqual("line count", 2, len(lines))
        self.assertLoggedEqual("first utterance", "速。", lines[0].text)
        self.assertLoggedEqual("first extended from its word into the pause", timedelta(seconds=100.8), lines[0].end)
        self.assertLoggedEqual("second utterance", "杀了！", lines[1].text)

    def test_mismatched_words_leave_the_part_whole(self):
        """Words that do not transcribe the part cannot be trusted to split it."""
        parts = [_part("要不要跳进去？", 0.0, 19.0)]
        words = [_word("别的", 1.0, 1.8), _word("东西", 1.8, 2.5)]
        builder = _default_builder()
        with self.assertLogs(level=logging.WARNING):
            lines = self._lines(parts, words, builder)
            flagged = builder.WarnIfOverlong(lines[0])

        self.assertLoggedEqual("line count", 1, len(lines))
        self.assertLoggedEqual("span kept", timedelta(seconds=119.0), lines[0].end)
        self.assertLoggedEqual("flagged", True, flagged)

    def test_words_are_matched_to_parts_by_text(self):
        """Word timings that disagree with the part spans do not move words between parts."""
        parts = [_part("好。", 0.0, 1.0), _part("你好，朋友。我们走吧！", 1.0, 9.0)]
        words = ([_word("好", 5.0, 5.2), _word("。", 5.2, 5.2)]
                 + _uniform_words(["你好", "，", "朋友", "。", "我们", "走吧", "！"], seconds_each=6.0 / 7, start=1.0))
        lines = self._lines(parts, words)

        self.assertLoggedEqual("line count", 3, len(lines))
        self.assertLoggedEqual("first part untouched", "好。", lines[0].text)
        self.assertLoggedEqual("second part split", "你好，朋友。", lines[1].text)

    def test_overlapping_lines_merge_as_dialogue(self):
        """Two full lines over the same span become one subtitle, one row each, even with one speaker ID."""
        parts = [_part("Ái da, dâm cung rồi.", 0.0, 1.72, "0"), _part("哎呀，杨公了。", 0.0, 1.72, "0")]
        builder = TranscriptionLineBuilder(LineSettings(max_line_chars=120, max_line_seconds=4.0, min_line_seconds=0.8))
        lines = self._lines(parts, [], builder)

        self.assertLoggedEqual("line count", 1, len(lines))
        self.assertLoggedEqual("dialogue rows", "- Ái da, dâm cung rồi.\n- 哎呀，杨公了。", lines[0].text)

    def test_overlap_merges_even_when_speakers_are_kept_apart(self):
        """Overlapping speakers still share a subtitle when speaker merging is disabled."""
        parts = [_part("我们走吧。", 0.0, 2.0, "0"), _part("等一下！", 1.0, 3.0, "1")]
        builder = TranscriptionLineBuilder(LineSettings(max_line_chars=120, max_line_seconds=4.0,
                                                        can_merge_different_speakers=False))
        lines = self._lines(parts, [], builder)

        self.assertLoggedEqual("line count", 1, len(lines))

    def test_parts_are_placed_by_time(self):
        """A part listed after one it precedes is ordered and merged by its time, not its position."""
        parts = [_part("好啊。", 1.0, 2.0, "1"), _part("你一千万赏金都没事。", 0.0, 1.5, "1")]
        lines = self._lines(parts, [])

        self.assertLoggedEqual("line count", 1, len(lines))
        self.assertLoggedEqual("start", timedelta(seconds=100.0), lines[0].start)
        self.assertLoggedEqual("rows in time order", "- 你一千万赏金都没事。\n- 好啊。", lines[0].text)

    def test_separate_parts_come_out_in_time_order(self):
        """Parts that do not overlap are still emitted in time order."""
        parts = [_part("我们走吧。", 5.0, 7.0), _part("等一下！", 0.0, 2.0)]
        lines = self._lines(parts, [])

        self.assertLoggedEqual("line count", 2, len(lines))
        self.assertLoggedEqual("earliest first", "等一下！", lines[0].text)

    def test_runaway_span_does_not_draw_in_later_lines(self):
        """A line spanning the whole chunk overlaps everything, but must not chain every later line into one run."""
        parts = [_part("嗨", 0.0, 50.0), _part("你好", 1.0, 3.0),
                 _part("哎呀", 10.0, 10.5), _part("是", 10.9, 11.2), _part("我们走吧。", 20.0, 22.0)]
        with self.assertLogs(level=logging.WARNING):
            lines = self._lines(parts, [])

        texts = [line.text for line in lines]
        self.assertLoggedIn("brief fragments still pair up", "哎呀是", texts)
        self.assertLoggedIn("distant line stays its own", "我们走吧。", texts)

    def test_fragment_before_another_speaker_extends_instead_of_merging(self):
        """A complete brief turn with room after it is lengthened, not made into dialogue with the next speaker."""
        parts = [_part("不正，华西來的師傅來㗎嘛，點解立面插去㗎？", 1.275, 4.554, "0"),
                 _part("我插你㗎。", 4.835, 5.554, "0"),
                 _part("佢哋選了我成千萬奖金啊，正要插就算比面啊。", 5.835, 8.755, "1")]
        lines = self._lines(parts, [])

        self.assertLoggedEqual("line count", 3, len(lines))
        self.assertLoggedEqual("fragment alone", "我插你㗎。", lines[1].text)
        self.assertLoggedEqual("fragment extended", timedelta(seconds=105.635), lines[1].end)

    def test_fragment_without_room_still_joins_the_next_speaker(self):
        """With no pause to extend into, the fragment is still rescued by merging."""
        parts = [_part("不正，华西來的師傅來㗎嘛。", 1.0, 4.0, "0"),
                 _part("我插你㗎。", 4.2, 4.7, "0"),
                 _part("佢哋選了我成千萬奖金啊。", 4.8, 7.0, "1")]
        lines = self._lines(parts, [])

        self.assertLoggedEqual("line count", 2, len(lines))
        self.assertLoggedEqual("dialogue", "- 我插你㗎。\n- 佢哋選了我成千萬奖金啊。", lines[1].text)

    def test_isolated_fragment_extends_into_the_pause(self):
        """A brief line alone between pauses is shown for the minimum duration."""
        parts = [_part("你好。", 0.0, 2.0), _part("嗯。", 3.0, 3.2), _part("我们走吧。", 6.0, 8.0)]
        lines = self._lines(parts, [])

        self.assertLoggedEqual("line count", 3, len(lines))
        self.assertLoggedEqual("extended end", timedelta(seconds=103.8), lines[1].end)

    def test_extension_leaves_the_minimum_gap(self):
        """A fragment that cannot reach the minimum before the next line keeps its own span."""
        parts = [_part("你好。", 0.0, 2.0, "0"), _part("嗯。", 3.0, 3.2, "0"), _part("我们走吧。", 3.78, 6.0, "1")]
        lines = self._lines(parts, [])

        fragment = next(line for line in lines if line.text == "嗯。")
        self.assertLoggedEqual("span kept", timedelta(seconds=103.2), fragment.end)

    def test_last_line_extends_no_further_than_the_chunk(self):
        """The final fragment of a chunk is only extended within the chunk."""
        segment = TranscriptionSegment(start=timedelta(seconds=100), end=timedelta(seconds=103.5), text="你好。嗯。",
                                       language="Chinese", parts=[_part("你好。", 0.0, 2.0), _part("嗯。", 3.0, 3.2)])
        lines = _default_builder().LinesForSegment(segment)

        self.assertLoggedEqual("fragment unextended", timedelta(seconds=103.2), lines[-1].end)

    def test_overlap_respects_the_line_limits(self):
        """Overlapping lines too long to share a subtitle stay apart."""
        parts = [_part("我们走吧。", 0.0, 3.0), _part("等一下！", 2.0, 5.0)]
        lines = self._lines(parts, [])

        self.assertLoggedEqual("line count", 2, len(lines))

    def test_split_keeps_opening_punctuation_with_its_sentence(self):
        """A part split at its words puts an opening question mark at the start of the next piece."""
        parts = [_part("¿Te vas ahora? ¿Por qué no te quedas?", 0.0, 8.0)]
        words = _uniform_words(["Te", "vas", "ahora", "Por", "qué", "no", "te", "quedas"], seconds_each=0.8)
        lines = self._lines(parts, words)

        self.assertLoggedEqual("texts", ["¿Te vas ahora?", "¿Por qué no te quedas?"], [line.text for line in lines])

    def test_words_missing_characters_still_split_the_part(self):
        """Words that drop a character and all punctuation still split a long part, and every character is kept."""
        parts = [_part("你好，朋友。我们走吧！", 0.0, 8.0)]
        words = _uniform_words(["你好", "友", "我们", "走吧"], seconds_each=1.5)
        lines = self._lines(parts, words)

        self.assertLoggedEqual("line count", 2, len(lines))
        self.assertLoggedEqual("first piece", "你好，朋友。", lines[0].text)
        self.assertLoggedEqual("second piece", "我们走吧！", lines[1].text)


class TestTimingCorrection(LoggedTestCase):
    """A line too short for its text is extended into the pause after it, when the provider's timings call for correction."""
    SENTENCE = "Cuando estoy nerviosa es aún peor."

    def _lines(self, parts : list[TranscriptionSegment], factor : float, chunk_end : float = 160.0) -> list[TranscriptionSegment]:
        segment = TranscriptionSegment(start=timedelta(seconds=100), end=timedelta(seconds=chunk_end),
                                       text=''.join(part.text for part in parts), language="Spanish", parts=parts)
        builder = TranscriptionLineBuilder(LineSettings(max_line_chars=120, max_line_seconds=4.0,
                                                        timing_correction_factor=factor))
        return builder.LinesForSegment(segment)

    def _speech(self, factor : float = 1.0) -> timedelta:
        return timedelta(seconds=factor * EstimateSpeechSeconds(self.SENTENCE))

    def test_provider_timing_is_trusted_by_default(self):
        """With no correction, a line keeps the span its provider gave it."""
        lines = self._lines([_part(self.SENTENCE, 0.0, 1.4), _part("Horrible.", 5.0, 6.0)], factor=0.0)

        self.assertLoggedEqual("end kept", timedelta(seconds=101.4), lines[0].end)

    def test_short_line_extends_towards_its_speaking_time(self):
        """A line shorter than its corrected speaking time is extended to it, and only its end moves."""
        lines = self._lines([_part(self.SENTENCE, 0.0, 1.4), _part("Horrible.", 5.0, 6.0)], factor=0.9)

        self.assertLoggedEqual("line count", 2, len(lines))
        self.assertLoggedEqual("start kept", timedelta(seconds=100), lines[0].start)
        self.assertLoggedEqual("extended end", timedelta(seconds=100) + self._speech(0.9), lines[0].end)
        self.assertLoggedEqual("next line untouched", timedelta(seconds=105), lines[1].start)

    def test_extension_stops_short_of_the_next_line(self):
        """A pause too short for the whole correction is used up to the minimum gap before the next line."""
        lines = self._lines([_part(self.SENTENCE, 0.0, 1.4), _part("Horrible.", 1.8, 2.8)], factor=1.0)

        self.assertLoggedEqual("line count", 2, len(lines))
        self.assertLoggedEqual("end before the next line", timedelta(seconds=101.75), lines[0].end)

    def test_extension_stays_within_the_chunk(self):
        """The last line of a chunk is only extended as far as the chunk's end."""
        lines = self._lines([_part(self.SENTENCE, 0.0, 1.4)], factor=1.0, chunk_end=101.6)

        self.assertLoggedEqual("end at the chunk's end", timedelta(seconds=101.6), lines[0].end)

    def test_imperceptible_correction_is_skipped(self):
        """A correction smaller than the threshold leaves the line as it was."""
        duration = self._speech().total_seconds() - MIN_TIMING_CORRECTION.total_seconds() / 2
        lines = self._lines([_part(self.SENTENCE, 0.0, duration), _part("Horrible.", 5.0, 6.0)], factor=1.0)

        self.assertLoggedEqual("end kept", timedelta(seconds=100) + timedelta(seconds=duration), lines[0].end)

    def test_line_long_enough_for_its_text_is_left_alone(self):
        """A line already lasting its corrected speaking time is never shortened."""
        lines = self._lines([_part(self.SENTENCE, 0.0, 3.0), _part("Horrible.", 5.0, 6.0)], factor=1.0)

        self.assertLoggedEqual("end kept", timedelta(seconds=103), lines[0].end)

    def test_correction_never_merges_lines(self):
        """Lines too short for their text keep their own lines, even when they could be merged."""
        parts = [_part(self.SENTENCE, 0.0, 1.4), _part("Nadie debía saber nada.", 1.5, 2.4)]
        uncorrected = self._lines(parts, factor=0.0)
        corrected = self._lines(parts, factor=1.0)

        self.assertLoggedEqual("line count", len(uncorrected), len(corrected))
        self.assertLoggedEqual("texts", [line.text for line in uncorrected], [line.text for line in corrected])


class TestDerivedParts(LoggedTestCase):
    """A transcript with words but no provider parts is cut into parts timed by its words."""
    def _lines(self, text : str, words : list[WordTiming],
               builder : TranscriptionLineBuilder|None = None) -> list[TranscriptionSegment]:
        segment = TranscriptionSegment(start=timedelta(seconds=100), end=timedelta(seconds=160),
                                       text=text, language="Chinese", words=words)
        return (builder or _default_builder()).LinesForSegment(segment)

    def test_transcript_characters_missing_from_the_words_are_kept(self):
        """The transcript supplies the text, including characters the words dropped."""
        words = [_word("杀", 0.0, 0.2), _word("精", 0.2, 0.4), _word("细", 0.6, 0.8), _word("佬", 0.8, 1.0)]
        lines = self._lines("杀精人，细佬。", words)

        self.assertLoggedEqual("line count", 1, len(lines))
        self.assertLoggedEqual("text", "杀精人，细佬。", lines[0].text)

    def test_parts_end_at_sentence_punctuation(self):
        """Words without punctuation are cut where the transcript ends a sentence."""
        words = _uniform_words(["你", "好"], seconds_each=0.2) + _uniform_words(["我", "们", "走", "吧"], 0.2, start=1.5)
        lines = self._lines("你好。我们走吧！", words)

        self.assertLoggedEqual("line count", 2, len(lines))
        self.assertLoggedEqual("first text", "你好。", lines[0].text)
        self.assertLoggedEqual("second text", "我们走吧！", lines[1].text)
        self.assertLoggedEqual("second starts at its first word", timedelta(seconds=101.5), lines[1].start)

    def test_pause_inside_a_sentence_does_not_cut_it(self):
        """With punctuation to go by, a pause mid-sentence leaves the sentence whole."""
        words = [_word("我", 0.0, 0.2), _word("们", 0.2, 0.4), _word("走", 0.4, 0.6), _word("吧", 2.0, 2.2)]
        lines = self._lines("我们走，吧。", words)

        self.assertLoggedEqual("line count", 1, len(lines))

    def test_unpunctuated_transcript_is_cut_at_pauses(self):
        """Without punctuation, a pause in the words ends a part."""
        words = _uniform_words(["你", "好", "朋", "友"], seconds_each=0.2) + _uniform_words(["我", "们", "走", "吧"], 0.2, start=3.0)
        lines = self._lines("你好朋友我们走吧", words)

        self.assertLoggedEqual("texts", ["你好朋友", "我们走吧"], [line.text for line in lines])

    def test_unpunctuated_transcript_is_cut_at_speaker_changes(self):
        """Without punctuation, a change of speaker ends a part, and each part takes its words' speaker."""
        words = ([_word(char, 0.2 * index, 0.2 * (index + 1), "A") for index, char in enumerate("你好朋友")]
                 + [_word(char, 0.8 + 0.2 * index, 0.8 + 0.2 * (index + 1), "B") for index, char in enumerate("我们走吧")])
        lines = self._lines("你好朋友我们走吧", words)

        self.assertLoggedEqual("texts", ["你好朋友", "我们走吧"], [line.text for line in lines])
        self.assertLoggedEqual("speakers", ["A", "B"], [line.speaker for line in lines])

    def test_timed_punctuation_ends_its_part(self):
        """A punctuation word marks where its utterance ends, so the part runs to it."""
        words = [_word("你", 0.0, 0.1), _word("好", 0.1, 0.2), _word("？", 1.2, 1.3)] + _uniform_words(["走", "吧"], 0.2, start=3.0)
        lines = self._lines("你好？走吧。", words)

        self.assertLoggedEqual("first end", timedelta(seconds=101.3), lines[0].end)

    def test_punctuated_sentence_is_cut_where_the_speaker_changes(self):
        """A sentence voiced by two speakers becomes a part for each."""
        words = ([_word(char, 0.3 * index, 0.3 * (index + 1), "A") for index, char in enumerate("你好朋友")]
                 + [_word(char, 1.2 + 0.3 * index, 1.2 + 0.3 * (index + 1), "B") for index, char in enumerate("我们走吧")])
        lines = self._lines("你好朋友我们走吧。", words)

        self.assertLoggedEqual("speakers", ["A", "B"], [line.speaker for line in lines])
        self.assertLoggedEqual("texts", ["你好朋友", "我们走吧。"], [line.text for line in lines])

    def test_opening_punctuation_stays_with_the_text_it_opens(self):
        """A Spanish question mark opens the next speaker's line rather than closing the previous one."""
        words = ([_word("Tenemos", 0.0, 0.3, "A"), _word("que", 0.3, 0.5, "A"), _word("hablar", 0.5, 1.0, "A")]
                 + [_word("Hablar", 2.0, 2.5, "B")])
        lines = self._lines("Tenemos que hablar. ¿Hablar?", words)

        self.assertLoggedEqual("texts", ["Tenemos que hablar.", "¿Hablar?"], [line.text for line in lines])

    def test_long_part_is_split_at_its_words(self):
        """A derived part over the duration limit is split like a provider part."""
        text = "你好朋友我们走吧真的很好。"
        words = _uniform_words(list("你好朋友我们走吧真的很好"), seconds_each=0.5)
        lines = self._lines(text, words)

        self.assertLoggedGreater("split", len(lines), 1)
        self.assertLoggedEqual("text kept", text, ''.join(line.text for line in lines))
        for line in lines:
            self.assertLoggedLessEqual("within the limit", (line.end - line.start).total_seconds(), 4.0)

    def test_runaway_words_do_not_time_their_part(self):
        """Words stretched far beyond their text are ignored, so their sentence is placed by length instead."""
        words = ([_word("声", 7.36, 12.15), _word("咩", 16.94, 21.73)]
                 + _uniform_words(["我", "们", "走", "吧"], 0.2, start=30.0))
        lines = self._lines("好声咩？我们走吧。", words)

        self.assertLoggedEqual("first text", "好声咩？", lines[0].text)
        self.assertLoggedEqual("first starts with the chunk", timedelta(seconds=100), lines[0].start)
        self.assertLoggedLessEqual("first lasts about its speaking time", (lines[0].end - lines[0].start).total_seconds(), 1.0)
        self.assertLoggedEqual("second timed by its words", timedelta(seconds=130), lines[1].start)

    def test_squeezed_words_do_not_time_their_part(self):
        """With partial word coverage, words crammed into far less time than their text takes are ignored, like runaway words."""
        squeezed = [_word(char, 10.0 + 0.01 * index, 10.0 + 0.01 * (index + 1)) for index, char in enumerate("你好朋友")]
        words = squeezed + _uniform_words(["我", "们", "走", "吧"], 0.2, start=20.0)
        lines = self._lines("你好朋友。我们走吧。", words, self._partial())

        self.assertLoggedEqual("placed between its neighbours, not at the squeezed words", timedelta(seconds=100), lines[0].start)
        self.assertLoggedEqual("lasts its speaking time", timedelta(seconds=100 + EstimateSpeechSeconds("你好朋友。")), lines[0].end)

    @staticmethod
    def _partial(**settings) -> TranscriptionLineBuilder:
        """A builder for words that can miss stretches of the transcript, with no minimum line length to mask the timing."""
        return TranscriptionLineBuilder(LineSettings(max_line_chars=120, max_line_seconds=4.0, min_line_seconds=0.1,
                                                     word_coverage=WordCoverage.PARTIAL, **settings))

    def test_zero_length_words_still_place_their_part(self):
        """With complete word coverage, a word stamped with no duration still marks where its part was said."""
        words = [_word("Sí", 10.0, 10.0), _word("No", 12.0, 12.2)]
        lines = self._lines("Sí. No.", words, TranscriptionLineBuilder(LineSettings(max_line_chars=120, max_line_seconds=4.0)))

        self.assertLoggedEqual("placed at its word", timedelta(seconds=110), lines[0].start)

    def test_part_is_extended_to_hold_its_unmatched_text(self):
        """With partial word coverage, a part is extended to hold all its text, at the pace of its words."""
        words = [_word("对", 0.0, 0.1), _word("住", 0.1, 0.2)]
        lines = self._lines("对唔住对唔住，西伯。", words, self._partial())

        self.assertLoggedEqual("eight characters at 0.1s each", timedelta(seconds=100.8), lines[0].end)

    def test_complete_coverage_keeps_its_words_timing(self):
        """With complete word coverage, a part keeps the span of its words, however little of its text they spell."""
        words = [_word("对", 0.0, 0.1), _word("住", 0.1, 0.2)]
        builder = TranscriptionLineBuilder(LineSettings(max_line_chars=120, max_line_seconds=4.0, min_line_seconds=0.1))
        lines = self._lines("对唔住对唔住，西伯。", words, builder)

        self.assertLoggedEqual("words' own end", timedelta(seconds=100.2), lines[0].end)

    def test_slow_words_do_not_stretch_the_part(self):
        """Words spoken with a pause between them set a pace no slower than normal speech."""
        words = [_word("对", 0.0, 0.2), _word("住", 2.0, 2.2)]
        lines = self._lines("对唔住对唔住，西伯。", words, self._partial())

        self.assertLoggedEqual("words' own end, already longer than the text needs", timedelta(seconds=102.2), lines[0].end)

    def test_well_covered_part_keeps_its_words_timing(self):
        """A part its words spell almost entirely is not extended, however briefly they were spoken."""
        words = _uniform_words(list("对唔住对唔住"), seconds_each=0.1) + _uniform_words(["我", "们"], 0.2, start=5.0)
        lines = self._lines("对唔住对唔住。我们。", words, self._partial())

        self.assertLoggedEqual("words' own end", timedelta(seconds=100.6), lines[0].end)

    def test_leading_text_moves_the_start_earlier(self):
        """With partial word coverage, text before a part's first matched word starts it earlier, at the pace of its words."""
        words = [_word("西", 10.0, 10.1), _word("伯", 10.1, 10.2)]
        lines = self._lines("喂，同我冇关噶喎西伯。", words, self._partial())

        self.assertLoggedEqual("seven characters earlier at 0.1s each", timedelta(seconds=109.3), lines[0].start)

    def test_leading_text_stops_short_of_the_part_before(self):
        """A part moved earlier never starts before the previous part has ended."""
        words = [_word("你", 0.0, 0.3), _word("好", 0.3, 0.6), _word("西", 1.5, 1.7), _word("伯", 1.7, 1.9)]
        lines = self._lines("你好。喂，同我冇关噶喎西伯。", words, self._partial(can_merge_different_speakers=False))

        self.assertLoggedEqual("line count", 2, len(lines))
        self.assertLoggedLessEqual("no overlap", lines[0].end, lines[1].start)

    def test_word_matching_one_character_does_not_cover_its_part(self):
        """With partial word coverage, a word counts only the characters it matched, so its part is still extended."""
        words = [_word("张三李四王五好赵钱孙", 10.0, 10.3)]
        lines = self._lines("你好朋友我们走吧。", words, self._partial())

        self.assertLoggedGreater("extended past the word", lines[0].end, timedelta(seconds=110.3))

    def test_full_stops_end_sentences_only_when_asked(self):
        """A full stop ends a sentence where the text breaks after it, and only with SentenceEnds.ALL."""
        text = "It costs 3.5 dollars. That's all."
        self.assertLoggedEqual("all ends", ["It costs 3.5 dollars.", "That's all."],
                               [text[start:end].strip() for start, end in SentenceRanges(text, SentenceEnds.ALL)])
        self.assertLoggedEqual("strong ends", [text], [text[start:end] for start, end in SentenceRanges(text)])

    def test_abbreviations_do_not_end_sentences(self):
        """Initials and dotted abbreviations do not end a sentence at their full stop."""
        cases = {
            "We met J. Smith there. It rained.": ["We met J. Smith there.", "It rained."],
            "He moved to the U.S.A. last year.": ["He moved to the U.S.A. last year."],
            "Bring snacks, e.g. crisps. Then go.": ["Bring snacks, e.g. crisps.", "Then go."],
            "Meet me at 3. Then we go.": ["Meet me at 3.", "Then we go."],
            "Wait. I know.": ["Wait.", "I know."],
        }

        for text, expected in cases.items():
            self.assertLoggedEqual("sentences", expected,
                                   [text[start:end].strip() for start, end in SentenceRanges(text, SentenceEnds.ALL)],
                                   input_value=text)

    def test_transcript_without_words_is_cut_at_full_stops(self):
        """With no words to divide it, a transcript is cut at full stops, and its sentences spread across the chunk."""
        with self.assertLogs(level=logging.INFO):
            lines = self._lines("First sentence. Second sentence.", [])

        self.assertLoggedEqual("texts", ["First sentence.", "Second sentence."], [line.text for line in lines])
        self.assertLoggedGreater("second placed later in the chunk", lines[1].start, timedelta(seconds=120))

    def test_unrelated_words_are_not_used(self):
        """Words that match nothing in the transcript leave it to be placed by length."""
        words = [_word("别的", 1.0, 1.8), _word("东西", 1.8, 2.5)]
        with self.assertLogs(level=logging.INFO):
            lines = self._lines("要不要跳进去？", words)

        self.assertLoggedEqual("line count", 1, len(lines))
        self.assertLoggedEqual("text", "要不要跳进去？", lines[0].text)
        self.assertLoggedLessEqual("within the limit", (lines[0].end - lines[0].start).total_seconds(), 4.0)


class TestLineBuilderWiring(LoggedTestCase):
    def test_builder_limits_come_from_settings(self):
        """The coordinator configures its line builder from transcription settings."""
        provider = FakeTranscriptionProvider()
        coordinator = TranscriptionCoordinator(provider, SettingsType({
            'max_characters': 42,
            'max_line_duration': 5.5,
            'min_split_chars': 6,
            'min_gap': 0.1}))

        self.assertLoggedEqual("max chars", 42, coordinator.line_builder.settings.max_line_chars)
        self.assertLoggedEqual("max seconds", 5.5, coordinator.line_builder.settings.max_line_seconds)
        self.assertLoggedEqual("min split chars", 6, coordinator.line_builder.settings.min_split_chars)
        self.assertLoggedEqual("min gap", 0.1, coordinator.line_builder.settings.min_gap)

    def test_builder_takes_the_provider_word_coverage(self):
        """A provider whose words can miss stretches of the transcript configures the builder for it."""
        provider = FakeTranscriptionProvider()
        provider.word_coverage = WordCoverage.PARTIAL
        coordinator = TranscriptionCoordinator(provider)

        self.assertLoggedEqual("word coverage", WordCoverage.PARTIAL, coordinator.line_builder.settings.word_coverage)

    def test_builder_takes_the_provider_timing_correction(self):
        """A provider's timing correction factor configures the builder."""
        provider = FakeTranscriptionProvider(SettingsType({'timing_correction_factor': 0.6}))
        coordinator = TranscriptionCoordinator(provider)

        self.assertLoggedEqual("timing correction", 0.6, coordinator.line_builder.settings.timing_correction_factor)

    def test_builder_defaults(self):
        """Missing settings fall back to the documented defaults."""
        coordinator = TranscriptionCoordinator(FakeTranscriptionProvider())

        self.assertLoggedEqual("max chars", 120, coordinator.line_builder.settings.max_line_chars)
        self.assertLoggedEqual("max seconds", 4.0, coordinator.line_builder.settings.max_line_seconds)
        self.assertLoggedEqual("min split chars", 3, coordinator.line_builder.settings.min_split_chars)
        self.assertLoggedEqual("no timing correction", 0.0, coordinator.line_builder.settings.timing_correction_factor)

class TestChunkSettings(LoggedTestCase):
    """The coordinator plans chunks with the provider's chunk bounds."""

    def _provider(self) -> FakeTranscriptionProvider:
        provider = FakeTranscriptionProvider()
        provider.settings['min_chunk_seconds'] = 20.0
        provider.settings['max_chunk_seconds'] = 90.0
        return provider

    def test_coordinator_takes_provider_chunk_bounds(self):
        """The chunker is planned with the provider's chunk bounds."""
        coordinator = TranscriptionCoordinator(self._provider())

        self.assertLoggedEqual("chunker min", 20.0, coordinator.chunker.min_chunk_seconds)
        self.assertLoggedEqual("chunker max", 90.0, coordinator.chunker.max_chunk_seconds)

    def test_run_settings_override_provider_chunk_bounds(self):
        """Explicit bounds for the run win over the provider's."""
        coordinator = TranscriptionCoordinator(self._provider(), SettingsType({
            'min_chunk_seconds': 5.0, 'max_chunk_seconds': 45.0}))

        self.assertLoggedEqual("run min", 5.0, coordinator.chunker.min_chunk_seconds)
        self.assertLoggedEqual("run max", 45.0, coordinator.chunker.max_chunk_seconds)


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
        resolved = TranscriptionProvider.ResolveProviderSettings(
            "OpenRouter", SettingsType(), options.get_dict('provider_settings'))

        self.assertLoggedEqual("shared key", "shared-key", resolved.get_str('api_key'))
        self.assertLoggedEqual("no shared server", None, resolved.get_str('server_address'))
        self.assertLoggedEqual("no shared model", None, resolved.get_str('model'))

    def test_own_namespace_wins(self):
        """Saved transcription settings take precedence over shared ones."""
        options = self._options()
        options.provider_settings['OpenRouter Transcription'] = SettingsType({
            'model': 'openai/whisper-large-v3',
        })
        resolved = TranscriptionProvider.ResolveProviderSettings(
            "OpenRouter", SettingsType(), options.get_dict('provider_settings'))

        self.assertLoggedEqual("own model", "openai/whisper-large-v3", resolved.get_str('model'))
        self.assertLoggedEqual("shared key", "shared-key", resolved.get_str('api_key'))

    def test_settings_key_format(self):
        """Transcription namespaces are clearly separated."""
        self.assertLoggedEqual(
            "key format", "OpenRouter Transcription",
            TranscriptionProvider.SettingsKey("OpenRouter"))

    def test_information_composition_matrix(self):
        """Info text composes ffmpeg guidance with provider content."""
        keyed = FakeTranscriptionProvider(SettingsType({'api_key': 'k'}))
        keyless = FakeTranscriptionProvider(SettingsType())

        walkthrough = keyless.GetInformation(ffmpeg_available=True)
        base = keyed.GetInformation(ffmpeg_available=True)
        unknown = keyed.GetInformation(ffmpeg_available=None)
        missing = keyed.GetInformation(ffmpeg_available=False)

        self.assertLoggedEqual("walkthrough selected", "Test walkthrough", walkthrough)
        self.assertLoggedEqual("proven has no ffmpeg paragraph", None, base)
        self.assertLoggedIn("unknown guidance", "ffmpeg", (unknown or "").casefold())
        self.assertLoggedIn("missing guidance", "ffmpeg", (missing or "").casefold())

    def test_language_warning_in_information(self):
        """A hint the provider rejects surfaces as a warning paragraph; usable hints add nothing."""
        class PickyProvider(FakeTranscriptionProvider):
            def ResolveLanguageCode(self, language : str|None, display_language : str|None = None) -> str|None:
                if language and language.casefold() != 'english':
                    raise SubtitleError(f"Unrecognised language '{language}'")
                return 'en' if language else None

        picky = PickyProvider(SettingsType({'api_key': 'k', 'language': 'Klingon'}))
        self.assertLoggedEqual("warning text", "Unrecognised language 'Klingon'", picky.LanguageWarning())
        self.assertLoggedIn("warning in information", "Klingon", picky.GetInformation(ffmpeg_available=True) or "")

        fine = PickyProvider(SettingsType({'api_key': 'k', 'language': 'English'}))
        self.assertLoggedIsNone("no warning", fine.LanguageWarning())
        self.assertLoggedIsNone("no information", fine.GetInformation(ffmpeg_available=True))

        lenient = FakeTranscriptionProvider(SettingsType({'api_key': 'k', 'language': 'Klingon'}))
        self.assertLoggedIsNone("default accepts free text", lenient.LanguageWarning())
        self.assertLoggedEqual("default trims hint", "Klingon", lenient.ResolveLanguageCode("  Klingon "))
        self.assertLoggedIsNone("default empty hint", lenient.ResolveLanguageCode("  "))

    def test_resolve_torch_device_never_imports(self):
        """Device resolution reads an already-imported module only."""
        self.assertLoggedEqual("absent module", "Unknown",
                               TranscriptionProvider.ResolveTorchDevice(None))

        class FakeCuda:
            def __init__(self, available : bool):
                self._available = available
            def is_available(self) -> bool:
                return self._available

        class FakeTorch:
            def __init__(self, available : bool):
                self.cuda = FakeCuda(available)

        self.assertLoggedEqual("cuda device", "cuda:0",
                               TranscriptionProvider.ResolveTorchDevice(FakeTorch(True)))
        self.assertLoggedEqual("cpu device", "cpu",
                               TranscriptionProvider.ResolveTorchDevice(FakeTorch(False)))
        self.assertLoggedEqual("broken module", "Unknown",
                               TranscriptionProvider.ResolveTorchDevice(object()))

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
            with self.assertLogs(level=logging.ERROR):
                outcome = coordinator.TranscribeMedia(media.name)

        self.assertLoggedEqual("failed status", TranscriptionStatus.FAILED, outcome.status)
        self.assertLoggedIn("no timed subtitles", "No timed", str(outcome.error))

        assert provider.client is not None  # Type narrowing for PyLance
        self.assertLoggedEqual("no requests sent", 0, provider.client.calls)

class TestTranscriptionCoordinator(LoggedTestCase):
    def _coordinator(self, texts : list[str]|None = None, words : list[WordTiming]|None = None,
                     parts : list[TranscriptionSegment]|None = None):
        provider = FakeTranscriptionProvider(SettingsType(), texts, words, parts=parts)
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
            outcome = coordinator.TranscribeMedia(media.name)
            subtitles = _subtitles_of(outcome)

        self.assertLoggedIsInstance("subtitles type", subtitles, Subtitles)
        self.assertLoggedEqual("line count", 2, subtitles.linecount)
        assert subtitles.originals is not None  # Type narrowing for PyLance
        self.assertLoggedEqual("first start", timedelta(seconds=0), subtitles.originals[0].start)
        self.assertLoggedEqual("second start", timedelta(seconds=6), subtitles.originals[1].start)
        assert provider.client is not None  # Type narrowing for PyLance
        self.assertLoggedEqual("client calls", 2, provider.client.calls)

    def test_capture_records_the_line_settings(self):
        """A capture records the line settings its run used, so a replay can reproduce them."""
        provider = FakeTranscriptionProvider(SettingsType({'timing_correction_factor': 0.6}), ["first line"], [_word("w", 0.0, 1.0)])
        provider.word_coverage = WordCoverage.PARTIAL

        with tempfile.TemporaryDirectory() as folder:
            capture_path = os.path.join(folder, "capture.json")
            coordinator = TranscriptionCoordinator(provider, SettingsType({'min_chunk_seconds': 1.0,
                                                                          'transcription_capture_path': capture_path}))
            stub_media(self, coordinator, [AudioChunk(start=timedelta(seconds=0), end=timedelta(seconds=4))])

            with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
                _subtitles_of(coordinator.TranscribeMedia(media.name))

            recorded = LoadCaptureLineSettings(capture_path)

        self.assertLoggedEqual("recorded settings", coordinator.line_builder.settings, recorded)

    def test_capture_without_line_settings_loads_none(self):
        """A capture from before line settings were recorded still loads, with none to replay."""
        with tempfile.TemporaryDirectory() as folder:
            capture_path = os.path.join(folder, "capture.json")
            with open(capture_path, 'w', encoding='utf-8') as file:
                json.dump({'provider': 'Gemini', 'media': None, 'segments': []}, file)

            recorded = LoadCaptureLineSettings(capture_path)

        self.assertLoggedIsNone("no recorded settings", recorded)

    def test_gate_refuses_untimed_provider(self):
        """Providers without timings are refused before spending anything."""
        provider = FakeTranscriptionProvider(SettingsType(), ["some text"], timestamps=False)
        coordinator = TranscriptionCoordinator(provider, SettingsType())

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            with self.assertLogs(level=logging.ERROR):
                outcome = coordinator.TranscribeMedia(media.name)

        self.assertLoggedEqual("failed status", TranscriptionStatus.FAILED, outcome.status)
        self.assertLoggedIn("provider named", "Fake Transcription", str(outcome.error))

    def test_untimed_results_kept_as_scene_lines(self):
        """Paid-for flat text is kept over true chunk spans, not thrown away."""
        coordinator, _unused_provider = self._coordinator(["first scene", "second scene"])
        stub_media(self, coordinator, [
            AudioChunk(start=timedelta(seconds=0), end=timedelta(seconds=2)),
            AudioChunk(start=timedelta(seconds=2), end=timedelta(seconds=4)),
        ])

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            outcome = coordinator.TranscribeMedia(media.name)
            subtitles = _subtitles_of(outcome)

        self.assertLoggedEqual("line count", 2, subtitles.linecount)
        assert subtitles.originals is not None  # Type narrowing for PyLance
        self.assertLoggedEqual("second span", timedelta(seconds=4), subtitles.originals[1].end)

    def test_no_speech_fails(self):
        """Media with nothing transcribable fails instead of an empty project."""
        coordinator, _unused_provider = self._coordinator(["", "   "])
        stub_media(self, coordinator, [
            AudioChunk(start=timedelta(seconds=0), end=timedelta(seconds=2)),
        ])

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            with self.assertLogs(level=logging.ERROR):
                outcome = coordinator.TranscribeMedia(media.name)

        self.assertLoggedEqual("failed status", TranscriptionStatus.FAILED, outcome.status)
        self.assertLoggedIsNone("no subtitles", outcome.subtitles)

    def test_segment_callback_receives_each_scene(self):
        """Per-chunk callback fires with timings for live progress display."""
        coordinator, _unused_provider = self._coordinator(["first line", "second line"], [_word("w", 0.0, 1.0)])
        stub_media(self, coordinator, [
            AudioChunk(start=timedelta(seconds=0), end=timedelta(seconds=4)),
            AudioChunk(start=timedelta(seconds=6), end=timedelta(seconds=10)),
        ])

        seen : list = []
        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            coordinator.events.segment.connect(lambda sender, segment: seen.append(segment), weak=False)
            coordinator.TranscribeMedia(media.name)

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
            coordinator.events.progress.connect(lambda sender, done, total, span: seen.append(span), weak=False)
            coordinator.TranscribeMedia(media.name)

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
            outcome = coordinator.TranscribeMedia(media.name)
            subtitles = _subtitles_of(outcome)

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

        def abort_after_first(sender, done : int, total : int, span : str) -> None:
            if done >= 1:
                coordinator.Abort()

        coordinator.events.progress.connect(abort_after_first)
        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            with self.assertLogs(level=logging.ERROR):
                outcome = coordinator.TranscribeMedia(media.name)
            subtitles = _subtitles_of(outcome)

        self.assertLoggedEqual("partial line count", 1, subtitles.linecount)

    def test_abort_before_anything_fails(self):
        """Cancelling with nothing transcribed fails rather than producing empty output."""
        coordinator, _unused_provider = self._coordinator(["first line"], [_word("w", 0.0, 1.0)])
        stub_media(self, coordinator, [
            AudioChunk(start=timedelta(seconds=0), end=timedelta(seconds=4)),
        ])
        coordinator.Abort()

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            with self.assertLogs(level=logging.ERROR):
                outcome = coordinator.TranscribeMedia(media.name)

        self.assertLoggedEqual("failed status", TranscriptionStatus.FAILED, outcome.status)

    def test_audio_track_info_label(self):
        """Track descriptors render a readable label."""
        info = AudioTrack(index=1, codec="ac3", language="chi")

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

    def test_scan_failure_keeps_partial_results(self):
        """A silence-scan error mid-run keeps transcribed chunks as INCOMPLETE."""
        coordinator, _unused_provider = self._coordinator(["first line"], [_word("w", 0.0, 1.0)])

        def failing_plan():
            yield AudioChunk(start=timedelta(seconds=0), end=timedelta(seconds=4))
            raise SubtitleError("silence scan failed")

        plan_patcher = patch.object(coordinator.chunker, "PlanChunksStream", return_value=failing_plan())
        read_patcher = patch.object(coordinator.extractor, "ReadChunkBytes", return_value=b"fake")
        plan_patcher.start()
        read_patcher.start()
        self.addCleanup(plan_patcher.stop)
        self.addCleanup(read_patcher.stop)

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            with self.assertLogs(level=logging.ERROR):
                outcome = coordinator.TranscribeMedia(media.name)
            subtitles = _subtitles_of(outcome)

        self.assertLoggedEqual("partial line count", 1, subtitles.linecount)
        self.assertLoggedEqual("incomplete status", TranscriptionStatus.INCOMPLETE, outcome.status)

    def test_initial_failure_stops_run(self):
        """A failure before any transcription stops immediately — no skipping."""
        coordinator, failing = self._failing_coordinator({1}, chunks=3)

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            with self.assertLogs(level=logging.ERROR):
                outcome = coordinator.TranscribeMedia(media.name)

        self.assertLoggedEqual("failed status", TranscriptionStatus.FAILED, outcome.status)
        self.assertLoggedIsNotNone("error recorded", outcome.error)
        self.assertLoggedEqual("stopped at failure", 1, failing.calls)

    def test_mid_run_failure_aborts_immediately(self):
        """A failure after transcription started aborts to prevent unfillable gaps."""
        coordinator, failing = self._failing_coordinator({2}, chunks=4)

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            with self.assertLogs(level=logging.ERROR):
                outcome = coordinator.TranscribeMedia(media.name)
            subtitles = _subtitles_of(outcome)

        self.assertLoggedEqual("partial lines retained", 1, subtitles.linecount)
        self.assertLoggedEqual("incomplete status", "incomplete", outcome.status.value)
        self.assertLoggedIsNotNone("failure retained", outcome.error)
        self.assertLoggedEqual("stopped at failure", 2, failing.calls)

    def test_postprocesses_transcription_text(self):
        """User normalizations apply to transcribed lines, timings untouched."""
        coordinator, _unused_provider = self._coordinator(["a — b"])
        stub_media(self, coordinator, [
            AudioChunk(start=timedelta(seconds=0), end=timedelta(seconds=4)),
        ])

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            outcome = coordinator.CreateTranscription(
                media.name, Options({'convert_wide_dashes': True}))
            subtitles = _subtitles_of(outcome)

        assert subtitles.originals is not None  # Type narrowing for PyLance
        self.assertLoggedEqual("dash normalised", "a - b", subtitles.originals[0].text)
        self.assertLoggedEqual("start kept", timedelta(seconds=0), subtitles.originals[0].start)
        self.assertLoggedEqual("end kept", timedelta(seconds=4), subtitles.originals[0].end)

    def test_discards_utterances_emptied_by_postprocessing(self) -> None:
        """Filler removal must not introduce empty source lines."""
        for texts in (["Um.", "Um, hello"], ["Um.", "Um."]):
            with self.subTest(texts=texts):
                coordinator, _unused_provider = self._coordinator(list(texts))
                stub_media(self, coordinator, [
                    AudioChunk(start=timedelta(seconds=0), end=timedelta(seconds=4)),
                    AudioChunk(start=timedelta(seconds=6), end=timedelta(seconds=10)),
                ])

                with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
                    outcome = coordinator.CreateTranscription(media.name, Options({
                        'remove_filler_words': True, 'filler_words': ['um'],
                        'postprocess_transcription': True,
                    }))
                    subtitles = _subtitles_of(outcome)

                originals = subtitles.originals or []
                expected = ["Hello"] if texts[1] == "Um, hello" else []
                self.assertLoggedEqual("nonempty source text", expected, [line.text for line in originals])
                if originals:
                    self.assertLoggedEqual("surviving start preserved", timedelta(seconds=6), originals[0].start)
                    self.assertLoggedEqual("surviving end preserved", timedelta(seconds=10), originals[0].end)

    def test_preprocesses_like_loaded_files(self):
        """Long flat lines split on duration under the post-process toggle."""
        text = "First sentence here. Second sentence here. Third sentence here. Fourth sentence here."
        # A provider part spanning the chunk, since a bare transcript is cut into timed parts
        part = TranscriptionSegment(start=timedelta(seconds=0), end=timedelta(seconds=60), text=text)
        coordinator, _unused_provider = self._coordinator([text], parts=[part])
        stub_media(self, coordinator, [
            AudioChunk(start=timedelta(seconds=0), end=timedelta(seconds=60)),
        ])

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            with self.assertLogs(level=logging.WARNING):
                outcome = coordinator.CreateTranscription(media.name, Options({
                    'postprocess_transcription': True, 'max_line_duration': 4.0}))
            subtitles = _subtitles_of(outcome)

        assert subtitles.originals is not None  # Type narrowing for PyLance
        self.assertLoggedGreater("line was split", len(subtitles.originals), 1)
        for line in subtitles.originals:
            self.assertLoggedLessEqual("split shorter than whole", line.duration.total_seconds(), 60.0)
        self.assertLoggedEqual("span start kept", timedelta(seconds=0), subtitles.originals[0].start)
        self.assertLoggedEqual("span end kept", timedelta(seconds=60), subtitles.originals[-1].end)

    def test_skips_preprocess_when_toggled_off(self):
        """Unchecking post-process keeps long flat lines whole."""
        text = "First sentence here. Second sentence here. Third sentence here. Fourth sentence here."
        # A provider part spanning the chunk, since a bare transcript is cut into timed parts
        part = TranscriptionSegment(start=timedelta(seconds=0), end=timedelta(seconds=60), text=text)
        coordinator, _unused_provider = self._coordinator([text], parts=[part])
        stub_media(self, coordinator, [
            AudioChunk(start=timedelta(seconds=0), end=timedelta(seconds=60)),
        ])

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            with self.assertLogs(level=logging.WARNING):
                outcome = coordinator.CreateTranscription(media.name, Options({
                    'postprocess_transcription': False}))
            subtitles = _subtitles_of(outcome)

        assert subtitles.originals is not None  # Type narrowing for PyLance
        self.assertLoggedEqual("line count", 1, len(subtitles.originals))



class TestTranscriptionRateLimit(LoggedTestCase):
    def test_unlimited_by_default(self):
        """No rate limit means no pacing sleep."""
        client = FakeTranscriptionClient()

        with patch("time.sleep") as mock_sleep:
            result = client.TranscribeChunk(b"fake-audio", "wav")

        self.assertLoggedEqual("transcript", "hello world", result.text)
        self.assertLoggedEqual("no pacing", 0, mock_sleep.call_count)

    def test_requests_paced_to_minimum_duration(self):
        """A 60/min limit paces each request to at least one second."""
        client = FakeTranscriptionClient(SettingsType({'rate_limit': 60.0}))

        clock = FakeClock()
        with patch("time.monotonic", side_effect=clock.Monotonic), \
             patch("time.sleep", side_effect=clock.Sleep) as mock_sleep:
            result = client.TranscribeChunk(b"fake-audio", "wav")

        total_slept = sum(call.args[0] for call in mock_sleep.call_args_list)
        self.assertLoggedEqual("transcript", "hello world", result.text)
        self.assertLoggedGreater("paced duration", total_slept, 0.99)

    def test_zero_disables_pacing(self):
        """An explicit zero limit behaves as unlimited."""
        client = FakeTranscriptionClient(SettingsType({'rate_limit': 0.0}))

        with patch("time.sleep") as mock_sleep:
            client.TranscribeChunk(b"fake-audio", "wav")

        self.assertLoggedEqual("no pacing", 0, mock_sleep.call_count)


class TestTranscriptionRetry(LoggedTestCase):
    """Verify base-class 429 retry in _PostRequestWithRetry / _PostJson."""

    def _make_response(self, status_code : int, body : str = '{}',
                       headers : dict|None = None) -> httpx.Response:
        """Build a minimal httpx.Response with the given status and body."""
        response = httpx.Response(status_code, text=body,
                                  headers=headers or {})
        return response

    def test_no_retry_on_success(self):
        """A 200 response is returned immediately without retry."""
        client = FakeTranscriptionClient()
        ok = self._make_response(200, '{"text": "hello"}')

        with patch.object(client, '_PostRequest', return_value=ok) as mock_post:
            result = client._PostJson("http://test/api")

        self.assertLoggedEqual("single request", 1, mock_post.call_count)
        self.assertLoggedEqual("payload text", "hello", result.get("text"))

    def test_retry_on_429_then_success(self):
        """A 429 followed by a 200 retries once and succeeds."""
        client = FakeTranscriptionClient()
        rate_limited = self._make_response(429, '{"error": "rate limited"}')
        ok = self._make_response(200, '{"text": "hello"}')

        clock = FakeClock()
        with patch.object(client, '_PostRequest', side_effect=[rate_limited, ok]) as mock_post, \
             patch("time.monotonic", side_effect=clock.Monotonic), \
             patch("time.sleep", side_effect=clock.Sleep):
            with self.assertLogs(level=logging.WARNING):
                result = client._PostJson("http://test/api")

        self.assertLoggedEqual("two requests", 2, mock_post.call_count)
        self.assertLoggedEqual("payload text", "hello", result.get("text"))

    def test_retry_respects_retry_after_header(self):
        """The Retry-After header controls the backoff delay."""
        client = FakeTranscriptionClient()
        rate_limited = self._make_response(429, '{"error": "rate limited"}',
                                           headers={'retry-after': '10'})
        ok = self._make_response(200, '{"text": "ok"}')

        clock = FakeClock()
        with patch.object(client, '_PostRequest', side_effect=[rate_limited, ok]), \
             patch("time.monotonic", side_effect=clock.Monotonic), \
             patch("time.sleep", side_effect=clock.Sleep) as mock_sleep:
            with self.assertLogs(level=logging.WARNING):
                client._PostJson("http://test/api")

        total_slept = sum(call.args[0] for call in mock_sleep.call_args_list)
        self.assertLoggedGreaterEqual("slept at least 10s", total_slept, 10.0)

    def test_gives_up_when_retries_exhausted(self):
        """Persistent 429 responses raise after exhausting retries."""
        client = FakeTranscriptionClient()
        rate_limited = self._make_response(429, '{"error": "rate limited"}')

        clock = FakeClock()
        with patch.object(client, '_PostRequest', return_value=rate_limited), \
             patch("time.monotonic", side_effect=clock.Monotonic), \
             patch("time.sleep", side_effect=clock.Sleep):
            with self.assertLogs(level=logging.WARNING):
                with self.assertRaises(SubtitleError):
                    client._PostJson("http://test/api")

    def test_gives_up_on_excessive_retry_after(self):
        """A Retry-After exceeding _GIVE_UP_SECONDS stops retrying immediately."""
        client = FakeTranscriptionClient()
        rate_limited = self._make_response(429, '{"error": "quota exceeded"}',
                                           headers={'retry-after': '600'})

        with patch.object(client, '_PostRequest', return_value=rate_limited) as mock_post:
            with self.assertRaises(SubtitleError):
                client._PostJson("http://test/api")

        self.assertLoggedEqual("single request (no retry)", 1, mock_post.call_count)

    def test_abort_during_retry_backoff(self):
        """An abort during retry sleep raises SubtitleError."""
        client = FakeTranscriptionClient()
        rate_limited = self._make_response(429, '{"error": "rate limited"}',
                                           headers={'retry-after': '30'})

        def abort_on_sleep(seconds : float) -> None:
            client.aborted = True
            raise SubtitleError("Transcription aborted")

        with patch.object(client, '_PostRequest', return_value=rate_limited), \
             patch("time.monotonic", return_value=0.0), \
             patch("time.sleep", side_effect=abort_on_sleep):
            with self.assertLogs(level=logging.WARNING):
                with self.assertRaises(SubtitleError):
                    client._PostJson("http://test/api")

    def test_no_retry_on_non_429_error(self):
        """A 500 error is not retried, just raised immediately."""
        client = FakeTranscriptionClient()
        error = self._make_response(500, '{"error": "internal"}')

        with patch.object(client, '_PostRequest', return_value=error) as mock_post:
            with self.assertRaises(SubtitleError):
                client._PostJson("http://test/api")

        self.assertLoggedEqual("single request", 1, mock_post.call_count)

    def test_subclass_can_override_retry_delay(self):
        """Subclasses can provide custom delay logic via _RetryDelayFromResponse."""
        client = FakeTranscriptionClient()

        # Override to always return a fixed 2-second delay
        client._RetryDelayFromResponse = lambda response, attempt: 2.0 if attempt < 1 else None

        rate_limited = self._make_response(429, '{"error": "rate limited"}')
        ok = self._make_response(200, '{"text": "ok"}')

        clock = FakeClock()
        with patch.object(client, '_PostRequest', side_effect=[rate_limited, ok]), \
             patch("time.monotonic", side_effect=clock.Monotonic), \
             patch("time.sleep", side_effect=clock.Sleep) as mock_sleep:
            with self.assertLogs(level=logging.WARNING):
                result = client._PostJson("http://test/api")

        total_slept = sum(call.args[0] for call in mock_sleep.call_args_list)
        self.assertLoggedEqual("payload text", "ok", result.get("text"))
        self.assertLoggedGreaterEqual("custom delay respected", total_slept, 2.0)


class TestTranscriptionProxySetting(LoggedTestCase):
    """A blank proxy must mean "no proxy" - httpx rejects an empty proxy URL with an obscure error."""

    def _post_proxy_kwarg(self, proxy : str) -> str|None:
        """POST once and return the proxy httpx.Client was constructed with."""
        client = FakeTranscriptionClient(SettingsType({'proxy': proxy}))
        response = httpx.Response(200, text='{}')

        with patch('httpx.Client') as mock_client_class:
            mock_client_class.return_value.__enter__.return_value.post.return_value = response
            client._PostRequest("http://test/api", json_body={'a': 1})

        return mock_client_class.call_args.kwargs.get('proxy')

    def test_blank_proxy_is_not_passed_to_httpx(self) -> None:
        """An empty or whitespace-only proxy setting is treated as unset."""
        for proxy in ["", "   "]:
            with self.subTest(proxy=proxy):
                self.assertLoggedIsNone("no proxy passed to httpx", self._post_proxy_kwarg(proxy), input_value=proxy)

    def test_configured_proxy_is_passed_to_httpx(self) -> None:
        """A configured proxy still reaches httpx."""
        self.assertLoggedEqual("proxy passed through", "http://localhost:8080",
                               self._post_proxy_kwarg("http://localhost:8080"))


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




if __name__ == '__main__':
    unittest.main()
