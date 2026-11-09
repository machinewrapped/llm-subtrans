"""Parts a client streams become lines and progress before its chunk is finished."""
from collections.abc import Callable, Generator
from datetime import timedelta
from unittest.mock import patch

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.SettingsType import SettingsType
from PySubtrans.Transcription.AudioChunker import AudioChunk
from PySubtrans.Transcription.LineSettings import LineSettings
from PySubtrans.Transcription.StreamedChunk import StreamedChunk
from PySubtrans.Transcription.TranscriptionCoordinator import TranscriptionCoordinator
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionResult, TranscriptionSegment
from tests.PySubtransTests.test_Transcription import FakeTranscriptionClient, FakeTranscriptionProvider

_CHUNK = AudioChunk(timedelta(seconds=30), timedelta(seconds=90))

# Short pauses that lines merge across, and long ones that release the parts before them
_PARTS = [
    (0.0, 1.2, 'S01', 'Hello there.'),
    (1.4, 1.8, 'S01', 'Hi.'),
    (4.0, 6.5, 'S02', 'How have you been lately?'),
    (6.7, 7.0, 'S01', 'Fine.'),
    (10.0, 12.0, 'S02', 'Good to hear it.'),
    (12.3, 14.0, 'S02', 'Shall we go?'),
]


def _Part(start : float, end : float, speaker : str, text : str) -> TranscriptionSegment:
    return TranscriptionSegment(start=timedelta(seconds=start), end=timedelta(seconds=end), text=text, speaker=speaker)


class StreamingClient(FakeTranscriptionClient):
    """Streams its parts before returning them all, noting how many lines had been added by the time the chunk finished."""

    def __init__(self, parts : list[TranscriptionSegment], lines_added : Callable[[], int]):
        super().__init__(texts=['\n'.join(part.text for part in parts)], parts=parts)
        self.lines_added : Callable[[], int] = lines_added
        self.lines_before_result : int = 0

    def _transcribe_chunk(self, audio_bytes : bytes, audio_format : str) -> TranscriptionResult:
        for part in self.parts:
            self._report_part(part)

        self.lines_before_result = self.lines_added()
        return super()._transcribe_chunk(audio_bytes, audio_format)


class TestTranscriptionStreaming(LoggedTestCase):
    """Streamed parts give the same lines as a finished chunk, sooner."""

    def setUp(self) -> None:
        super().setUp()
        self.parts = [_Part(*part) for part in _PARTS]

    def _run(self, streaming : bool) -> tuple[TranscriptionCoordinator, list[TranscriptionSegment], list[float], StreamingClient|None]:
        """Transcribe one 60-second chunk of a 120-second file, collecting lines and audio progress."""
        provider = FakeTranscriptionProvider(SettingsType(), parts=self.parts)
        with patch('PySubtrans.Transcription.AudioExtractor.CheckFfmpegAvailable'):
            coordinator = TranscriptionCoordinator(provider)

        lines : list[TranscriptionSegment] = []
        progress : list[float] = []
        coordinator.events.segment.connect(lambda sender, segment, overlong: lines.append(segment), weak=False)
        coordinator.events.audio_progress.connect(lambda sender, processed, total: progress.append(processed), weak=False)

        def PlanChunks(media_path : str, track_index : int, duration_cb : Callable[[timedelta], None]) -> Generator[AudioChunk, None, None]:
            duration_cb(timedelta(seconds=120))
            yield _CHUNK

        client = StreamingClient(self.parts, lambda: len(lines)) if streaming else None
        with patch.object(coordinator.chunker, 'PlanChunksStream', side_effect=PlanChunks), \
                patch.object(coordinator.extractor, 'ReadChunkBytes', return_value=b'audio'), \
                patch.object(coordinator.extractor, 'IsSilent', return_value=False):
            if client is not None:
                with patch.object(provider, 'GetTranscriptionClient', return_value=client):
                    coordinator.TranscribeMedia('readme.md')
            else:
                coordinator.TranscribeMedia('readme.md')

        return coordinator, lines, progress, client

    def test_streamed_lines_match_finished_chunk(self) -> None:
        """Releasing parts at long pauses changes no line, compared with transcribing the whole chunk first."""
        _coordinator, streamed, _progress, _client = self._run(streaming=True)
        _coordinator, finished, _progress, _client = self._run(streaming=False)

        def Lines(lines : list[TranscriptionSegment]) -> list[tuple[timedelta, timedelta, str]]:
            return [(line.start, line.end, line.text) for line in lines]

        self.assertLoggedEqual("same lines", Lines(finished), Lines(streamed))

    def test_lines_added_before_chunk_finishes(self) -> None:
        """Lines before a long pause are added while the chunk is still being transcribed."""
        _coordinator, lines, _progress, client = self._run(streaming=True)
        assert client is not None

        self.assertLoggedGreater("lines added early", client.lines_before_result, 0)
        self.assertLoggedLess("some lines wait for the chunk to finish", client.lines_before_result, len(lines))

    def test_progress_within_chunk(self) -> None:
        """Audio progress follows each streamed part, then the end of the chunk."""
        _coordinator, _lines, progress, _client = self._run(streaming=True)

        expected = [0.0, *(_CHUNK.start.total_seconds() + end for _start, end, _speaker, _text in _PARTS), _CHUNK.end.total_seconds()]
        self.assertLoggedEqual("progress positions", expected, progress)


class TestStreamedChunk(LoggedTestCase):
    """Parts are released only at pauses no line can merge across."""

    def test_release_at_long_pause(self) -> None:
        """A short pause holds the parts back, and a long one releases those before it."""
        stream = StreamedChunk(_CHUNK, LineSettings(max_line_chars=None, max_line_seconds=None), None)
        parts = [_Part(*part) for part in _PARTS[:3]]

        self.assertLoggedIsNone("first part held", stream.Add(parts[0]))
        self.assertLoggedIsNone("short pause holds", stream.Add(parts[1]))

        released = stream.Add(parts[2])
        assert released is not None
        self.assertLoggedEqual("parts before the pause released", parts[:2], released.parts)
        self.assertLoggedEqual("released count", 2, stream.released)

    def test_remainder_after_release(self) -> None:
        """Once parts are released, the rest of the result is what remains to become lines."""
        stream = StreamedChunk(_CHUNK, LineSettings(max_line_chars=None, max_line_seconds=None), None)
        parts = [_Part(*part) for part in _PARTS]
        for part in parts:
            stream.Add(part)

        remainder = stream.Remainder(TranscriptionResult(text='\n'.join(part.text for part in parts), parts=parts))
        assert remainder is not None
        self.assertLoggedEqual("unreleased parts remain", parts[stream.released:], remainder.parts)
        self.assertLoggedEqual("remainder ends with the chunk", _CHUNK.end, remainder.end)
