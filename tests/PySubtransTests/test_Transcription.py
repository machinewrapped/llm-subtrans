import array
import io
import math
import os
import tempfile
import unittest
import wave
from datetime import timedelta
from unittest.mock import patch

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Helpers.Tests import skip_if_debugger_attached
from PySubtrans.Options import Options
from PySubtrans.SettingsType import GuiSettingsType, SettingsType
from PySubtrans.SubtitleBuilder import SubtitleBuilder
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.Subtitles import Subtitles
from PySubtrans.Transcription.AudioExtractor import AudioChunk, AudioChunker, AudioExtractor, AudioTrack, SilenceStream
from PySubtrans.Transcription.TranscriptionAligner import WordTiming
from PySubtrans.Transcription.TranscriptionClient import TranscriptionClient
from PySubtrans.Transcription.TranscriptionCoordinator import TranscriptionCoordinator, TranscriptionOutcome, TranscriptionStatus
from PySubtrans.Transcription.TranscriptionLines import JoinWords, TranscriptionLineBuilder
from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionResult, TranscriptionSegment

from tests.Helpers import FakeClock


def setUpModule() -> None:
    """Unit fixtures supply media data and do not require FFmpeg executables."""
    availability_patcher = patch('PySubtrans.Transcription.AudioExtractor.CheckFfmpegAvailable')
    availability_patcher.start()
    unittest.addModuleCleanup(availability_patcher.stop)


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
                with SilenceStream(media.name) as stream:
                    events = list(stream)

        call_args = popen.call_args
        assert call_args is not None
        process_kwargs = call_args.kwargs
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
    return TranscriptionLineBuilder(max_line_chars=84, max_line_seconds=8.0, word_gap_split=0.5)


class TestWordGrouping(LoggedTestCase):
    def _builder(self):
        return _default_builder()

    def _scene_lines(self, builder : TranscriptionLineBuilder, text : str, words : list[WordTiming], language : str|None = "Chinese"):
        chunk = AudioChunk(start=timedelta(seconds=100), end=timedelta(seconds=160))
        segment = TranscriptionSegment(start=chunk.start, end=chunk.end, text=text, language=language, words=words)
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

    def test_no_words_stays_scene_line(self):
        """Untimed scenes stay one honest line over the chunk span."""
        builder = self._builder()
        lines = self._scene_lines(builder, "some text", [], language="Thai")

        self.assertLoggedEqual("line count", 1, len(lines))
        self.assertLoggedEqual("span preserved", timedelta(seconds=160), lines[0].end)

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

    def test_join_words_handles_quotes_apostrophes_and_hyphens(self):
        """Token joins preserve ordinary English punctuation conventions."""
        self.assertLoggedEqual("quoted phrase", 'He said "Hello world." Then',
                                JoinWords(['He', 'said', '"Hello', 'world."', 'Then']))
        self.assertLoggedEqual("apostrophe", "l'amour", JoinWords(["l'", "amour"]))
        self.assertLoggedEqual("hyphen", "well-known", JoinWords(['well-', 'known']))
        self.assertLoggedEqual("CJK punctuation", "你好，世界", JoinWords(['你好', '，', '世界']))

    def test_speaker_change_splits_lines(self):
        """Speaker turns break subtitle lines and label them."""
        words = [_word("yes", 0.0, 0.5, "A"), _word("no", 0.6, 1.0, "B")]
        lines = self._scene_lines(self._builder(), "yes no", words)

        self.assertLoggedEqual("line count", 2, len(lines))
        self.assertLoggedEqual("first speaker", "A", lines[0].speaker)
        self.assertLoggedEqual("second speaker", "B", lines[1].speaker)

    def test_sliver_across_pause_stays_separate(self):
        """A short interjection after seconds of silence keeps its own line."""
        words = [_word("seat?", 0.0, 1.0), _word("So...", 11.0, 11.3)]
        lines = self._scene_lines(self._builder(), "seat? So...", words)

        self.assertLoggedEqual("line count", 2, len(lines))
        self.assertLoggedEqual("first end", timedelta(seconds=101), lines[0].end)
        self.assertLoggedEqual("second start", timedelta(seconds=111), lines[1].start)
        self.assertLoggedEqual("second end", timedelta(seconds=111.3), lines[1].end)
        self.assertLoggedEqual("second text", "So...", lines[1].text)

    def test_sliver_after_short_pause_merges(self):
        """A fragment hard on the heels of the previous line still folds in."""
        words = [_word("yes", 0.0, 1.0, "A"), _word("um", 1.2, 1.4, "B")]
        lines = self._scene_lines(self._builder(), "yes um", words)

        self.assertLoggedEqual("line count", 1, len(lines))
        self.assertLoggedEqual("merged span", timedelta(seconds=101.4), lines[0].end)
        self.assertLoggedEqual("merged text", "- yes\n- um", lines[0].text)

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
        lines = builder.LinesForSegment(self._part_segment(20.0))

        self.assertLoggedEqual("line count", 1, len(lines))
        self.assertLoggedEqual("span kept", timedelta(seconds=120), lines[0].end)
        self.assertLoggedEqual("flagged", True, builder.WarnIfOverlong(lines[0]))

    def test_short_part_no_warning(self):
        """Ordinary parts pass without warnings."""
        builder = self._builder()
        lines = builder.LinesForSegment(self._part_segment(3.0))

        self.assertLoggedEqual("line count", 1, len(lines))
        self.assertLoggedEqual("flagged", False, builder.WarnIfOverlong(lines[0]))

    def test_whole_chunk_fallback_flags_warning(self):
        """A flat-text chunk span is flagged when it runs long."""
        builder = self._builder()
        segment = TranscriptionSegment(start=timedelta(seconds=100), end=timedelta(seconds=160),
                                       text="monologue", language="Chinese")
        lines = builder.LinesForSegment(segment)

        self.assertLoggedEqual("line count", 1, len(lines))
        self.assertLoggedEqual("flagged", True, builder.WarnIfOverlong(lines[0]))

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
        line = TranscriptionSegment(start=timedelta(seconds=100), end=timedelta(seconds=108),
                                    text="exactly eight seconds")

        self.assertLoggedEqual("flagged", False, builder.WarnIfOverlong(line))


class TestLineBuilderWiring(LoggedTestCase):
    def test_builder_limits_come_from_settings(self):
        """The coordinator configures its line builder from transcription settings."""
        provider = FakeTranscriptionProvider()
        coordinator = TranscriptionCoordinator(provider, SettingsType({
            'transcription_max_chars': 42,
            'transcription_max_line_seconds': 5.5,
            'transcription_gap_split': 0.25}))

        self.assertLoggedEqual("max chars", 42, coordinator.line_builder.max_line_chars)
        self.assertLoggedEqual("max seconds", 5.5, coordinator.line_builder.max_line_seconds)
        self.assertLoggedEqual("gap split", 0.25, coordinator.line_builder.word_gap_split)

    def test_builder_defaults(self):
        """Missing settings fall back to the documented defaults."""
        coordinator = TranscriptionCoordinator(FakeTranscriptionProvider())

        self.assertLoggedEqual("max chars", 84, coordinator.line_builder.max_line_chars)
        self.assertLoggedEqual("max seconds", 8.0, coordinator.line_builder.max_line_seconds)
        self.assertLoggedEqual("gap split", 0.5, coordinator.line_builder.word_gap_split)

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
            outcome = coordinator.TranscribeMedia(media.name)

        self.assertLoggedEqual("failed status", TranscriptionStatus.FAILED, outcome.status)
        self.assertLoggedIn("no timed subtitles", "No timed", str(outcome.error))

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
            outcome = coordinator.TranscribeMedia(media.name)
            subtitles = _subtitles_of(outcome)

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
            outcome = coordinator.TranscribeMedia(media.name)
            subtitles = _subtitles_of(outcome)

        self.assertLoggedEqual("partial line count", 1, subtitles.linecount)
        self.assertLoggedEqual("incomplete status", TranscriptionStatus.INCOMPLETE, outcome.status)

    def test_two_initial_failures_abort_run(self):
        """Two failures before anything works aborts instead of grinding chunks."""
        coordinator, failing = self._failing_coordinator({1, 2}, chunks=4)

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            outcome = coordinator.TranscribeMedia(media.name)

        self.assertLoggedEqual("failed status", TranscriptionStatus.FAILED, outcome.status)
        assert outcome.error is not None  # Type narrowing for PyLance
        # Note: str() prefers the wrapped error, the message carries ours
        self.assertLoggedIn("blocked message", "consecutive", outcome.error.message)
        self.assertLoggedEqual("stopped early", 2, failing.calls)

    def test_initial_failure_tolerated_when_next_succeeds(self):
        """A single failure before any transcription is tolerated."""
        coordinator, failing = self._failing_coordinator({1}, chunks=3)

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
            outcome = coordinator.TranscribeMedia(media.name)
            subtitles = _subtitles_of(outcome)

        self.assertLoggedEqual("line count", 2, subtitles.linecount)
        self.assertLoggedEqual("all chunks attempted", 3, failing.calls)

    def test_mid_run_failure_aborts_immediately(self):
        """A failure after transcription started aborts to prevent unfillable gaps."""
        coordinator, failing = self._failing_coordinator({2}, chunks=4)

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
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
        coordinator, _unused_provider = self._coordinator([text])
        stub_media(self, coordinator, [
            AudioChunk(start=timedelta(seconds=0), end=timedelta(seconds=60)),
        ])

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
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
        coordinator, _unused_provider = self._coordinator([text])
        stub_media(self, coordinator, [
            AudioChunk(start=timedelta(seconds=0), end=timedelta(seconds=60)),
        ])

        with tempfile.NamedTemporaryFile(suffix=".mkv") as media:
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
            result = client.TranscribeChunk(b"fake-audio", "wav", "en")

        self.assertLoggedEqual("transcript", "hello world", result.text)
        self.assertLoggedEqual("no pacing", 0, mock_sleep.call_count)

    def test_requests_paced_to_minimum_duration(self):
        """A 60/min limit paces each request to at least one second."""
        client = FakeTranscriptionClient(SettingsType({'rate_limit': 60.0}))

        clock = FakeClock()
        with patch("time.monotonic", side_effect=clock.Monotonic), \
             patch("time.sleep", side_effect=clock.Sleep) as mock_sleep:
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




if __name__ == '__main__':
    unittest.main()
