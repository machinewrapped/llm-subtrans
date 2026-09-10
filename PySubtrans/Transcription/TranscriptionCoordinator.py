from __future__ import annotations

import logging
import os
from collections.abc import Generator
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum

from PySubtrans.Helpers.Localization import _
from PySubtrans.Options import Options
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.SubtitleLine import SubtitleLine
from PySubtrans.SubtitleProcessor import SubtitleProcessor
from PySubtrans.Subtitles import Subtitles
from PySubtrans.Transcription.AudioExtractor import AudioExtractor, AudioChunk, AudioChunker, AudioTrack, CheckFfmpegAvailable
from PySubtrans.Transcription.TranscriptionClient import TranscriptionClient
from PySubtrans.Transcription.TranscriptionEvents import TranscriptionEvents
from PySubtrans.Transcription.TranscriptionLines import SpanLabel, TranscriptionLineBuilder
from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionSegment


class TranscriptionStatus(str, Enum):
    """Final state of a transcription run."""
    IDLE = "idle"
    COMPLETED = "completed"
    INCOMPLETE = "incomplete"
    FAILED = "failed"


@dataclass
class TranscriptionOutcome:
    """
    Result of one transcription run.

    COMPLETED and INCOMPLETE outcomes carry subtitles (partial ones for
    INCOMPLETE, which can be resumed by passing them back as
    prior_subtitles). FAILED outcomes carry the error and no subtitles.
    """
    status : TranscriptionStatus
    subtitles : Subtitles|None = None
    error : SubtitleError|None = None
    transcribed_lines : int = 0
    total_cost : float = 0.0

    @property
    def succeeded(self) -> bool:
        return self.status is TranscriptionStatus.COMPLETED


# Consecutive chunk failures before an empty run is treated as blocked
_MAX_INITIAL_FAILURES = 2


class _TranscriptionRun:
    """
    Mutable state for one TranscribeMedia call: accumulated lines,
    resume position, cost and failure bookkeeping.
    """
    def __init__(self, prior_subtitles : Subtitles|None):
        self.lines : list[SubtitleLine] = []
        self.line_number : int = 0
        self.resume_after : timedelta|None = None
        self.transcribed : int = 0
        self.chunks_done : int = 0
        self.consecutive_failures : int = 0
        self.had_failures : bool = False
        self.error : SubtitleError|None = None
        self.total_cost : float = 0.0
        self.audio_total_seconds : float = 0.0

        if prior_subtitles and prior_subtitles.originals:
            self.lines.extend(prior_subtitles.originals)
            self.line_number = max((line.number or 0) for line in self.lines)
            self.resume_after = prior_subtitles.originals[-1].end
            self.transcribed = prior_subtitles.linecount
            logging.info(_("Resuming transcription after {}").format(self.resume_after))

    def AlreadyDone(self, chunk : AudioChunk) -> bool:
        """Whether a prior run already covered this chunk."""
        return self.resume_after is not None and chunk.end <= self.resume_after

    def AddLine(self, segment : TranscriptionSegment) -> SubtitleLine|None:
        """
        Append a transcribed line, unless it precedes the resume point.
        Returns the new line, or None when skipped.
        """
        if self.resume_after is not None and segment.start < self.resume_after:
            return None

        self.line_number += 1
        metadata = {'speaker': segment.speaker} if segment.speaker else None
        line = SubtitleLine.Construct(self.line_number, segment.start, segment.end, segment.text, metadata)
        self.lines.append(line)
        self.transcribed += 1
        return line

    def AudioPosition(self, chunk : AudioChunk) -> float:
        """Seconds of audio processed once this chunk is done, clamped to the total."""
        return min(self.audio_total_seconds, max(0.0, chunk.end.total_seconds()))


class TranscriptionCoordinator:
    """
    End-to-end media to subtitles transcription.

    Extracts coherent audio chunks from a media file, transcribes each
    chunk with the provider client, and assembles timestamped subtitles.
    Has no GUI dependencies so CLI and library callers can use it directly.
    Subscribe to `events` for progress and per-line notifications; each run
    returns a TranscriptionOutcome describing what was produced.
    """
    def __init__(self, provider : TranscriptionProvider, settings : SettingsType|Options|None = None):
        self.provider : TranscriptionProvider = provider
        self.settings : SettingsType = SettingsType(settings or {})
        self.aborted : bool = False

        chunk_settings = SettingsType({
            'min_chunk_seconds': self.settings.get_float('min_chunk_seconds')
                or provider.recommended_min_chunk_seconds,
            'max_chunk_seconds': self.settings.get_float('max_chunk_seconds')
                or provider.recommended_max_chunk_seconds,
            'silence_min_duration': self.settings.get_float('silence_min_duration', 1.0),
        })
        self.chunker : AudioChunker = AudioChunker(chunk_settings)
        self.extractor : AudioExtractor = self.chunker.extractor
        self.line_builder : TranscriptionLineBuilder = TranscriptionLineBuilder(
            max_line_chars=self.settings.get_int('transcription_max_chars') or 84,
            max_line_seconds=self.settings.get_float('transcription_max_line_seconds') or 8.0,
            word_gap_split=self.settings.get_float('transcription_gap_split') or 0.5)
        self.events : TranscriptionEvents = TranscriptionEvents()

        self._active_client : TranscriptionClient|None = None

    @property
    def track_index(self) -> int:
        """Audio track to transcribe (0-based within audio streams)."""
        return self.settings.get_int('audio_track') or 0

    @property
    def language(self) -> str|None:
        """Spoken language hint for the transcription engine."""
        return self.settings.get_str('language') or self.provider.settings.get_str('language')

    @property
    def silence_skip_db(self) -> float:
        """Peak level below which chunks skip transcription entirely."""
        return self.settings.get_float('silence_skip_db') or -40.0

    def CheckRequirements(self, media_path : str) -> list[AudioTrack]:
        """
        Verify ffmpeg availability and return the media audio tracks.
        """
        CheckFfmpegAvailable()
        return self.extractor.ListAudioTracks(media_path)

    def PlanChunks(self, media_path : str) -> list[AudioChunk]:
        """
        Return the transcription chunk plan without extracting audio.
        """
        return self.chunker.PlanChunks(media_path, self.track_index)

    def TranscribeMedia(self, media_path : str, prior_subtitles : Subtitles|None = None) -> TranscriptionOutcome:
        """
        Transcribe a media file into timestamped subtitles.

        When *prior_subtitles* is supplied (from an earlier aborted run),
        already-transcribed chunks are skipped and the new lines are appended
        after the existing ones. Expected failures (missing media, an engine
        without timings, a blocked run, no speech) are reported as a FAILED
        outcome rather than raised.
        """
        if not media_path or not os.path.isfile(media_path):
            return self._failed(SubtitleError(_("Media file not found: {}").format(media_path)))

        try:
            client = self._start_client()
        except SubtitleError as e:
            return self._failed(e)

        run = _TranscriptionRun(prior_subtitles)

        def on_duration(duration : timedelta) -> None:
            run.audio_total_seconds = max(0.0, duration.total_seconds())
            if run.audio_total_seconds > 0.0:
                self.events.audio_progress.send(self, processed=0.0, total=run.audio_total_seconds)

        chunks = self.chunker.PlanChunksStream(media_path, self.track_index, duration_cb=on_duration)
        logging.info(_("Transcribing {} with {} (chunks stream in while silence detection runs)").format(
            os.path.basename(media_path), self.provider.name))

        try:
            self._run_chunks(run, client, media_path, chunks)
        except SubtitleError as e:
            # A blocked run with nothing transcribed is a failure; a
            # silence-scan failure mid-run must not discard already
            # transcribed (billed) chunks.
            if run.transcribed == 0:
                return self._failed(e)
            run.had_failures = True
            run.error = e
            logging.error(str(e))
        finally:
            chunks.close()
            self._active_client = None

        return self._finish_run(run, media_path)

    def CreateTranscription(self, media_path : str, options : Options|None = None,
                            prior_subtitles : Subtitles|None = None) -> TranscriptionOutcome:
        """Transcribe media and return the outcome with post-processed subtitles."""
        outcome = self.TranscribeMedia(media_path, prior_subtitles=prior_subtitles)

        if outcome.subtitles is not None and options is not None and options.get_bool('postprocess_transcription', True):
            self._process_transcription(outcome.subtitles, options)

        return outcome

    def Abort(self) -> None:
        """Stop transcription after the current chunk."""
        self.aborted = True
        if self._active_client is not None:
            self._active_client.AbortTranscription()

    def _failed(self, error : SubtitleError) -> TranscriptionOutcome:
        """Log and package a run that produced nothing usable."""
        logging.error(str(error))
        return TranscriptionOutcome(status=TranscriptionStatus.FAILED, error=error)

    def _start_client(self) -> TranscriptionClient:
        """
        Obtain the provider client, refusing engines that cannot time their output.
        """
        client = self.provider.GetTranscriptionClient(self.settings)
        self._active_client = client
        if not client.supports_timestamps:
            self._active_client = None
            raise SubtitleError(_(
                "'{}' cannot provide subtitle timings (no word or segment "
                "timestamps). Transcription without timings has no value "
                "here, so nothing was requested and no credits were spent."
            ).format(self.provider.name))
        return client

    def _run_chunks(self, run : _TranscriptionRun, client : TranscriptionClient, media_path : str,
                    chunks : Generator[AudioChunk, None, None]) -> None:
        """
        Transcribe each planned chunk in turn, honouring abort, resume and
        the failure policy. Partial results stay in run.lines.
        """
        def report_progress(done : int, chunk : AudioChunk) -> None:
            # Total is unknown while the plan streams in (0 signals that)
            self.events.progress.send(self, done=done, total=0, span=SpanLabel(chunk))

        def report_audio(chunk : AudioChunk) -> None:
            if run.audio_total_seconds > 0.0:
                self.events.audio_progress.send(self, processed=run.AudioPosition(chunk), total=run.audio_total_seconds)

        for done, chunk in enumerate(chunks):
            if self.aborted or client.aborted:
                # Keep everything transcribed so far: abandoning billed
                # work would be worse than partial results.
                logging.warning(_("Transcription cancelled after {done} chunks").format(done=done))
                run.had_failures = True
                break

            report_progress(done, chunk)
            if run.AlreadyDone(chunk):
                run.chunks_done += 1
                report_audio(chunk)
                continue

            try:
                segment, provider_responded = self._transcribe_chunk(run, client, media_path, chunk)
            except SubtitleError as e:
                if self._handle_chunk_failure(run, chunk, e):
                    break
            else:
                self._accept_chunk(run, segment, provider_responded)
            finally:
                report_audio(chunk)

    def _handle_chunk_failure(self, run : _TranscriptionRun, chunk : AudioChunk, error : SubtitleError) -> bool:
        """
        Record a chunk failure and decide whether the run must stop.

        Before anything has been transcribed, repeated failures indicate a
        systemic problem (credentials, model, endpoint) and the run fails
        fast with the real error. Once lines exist, any failure would leave
        an unfillable gap (resume appends after the last line, it cannot
        backfill), so the run stops there for the user to resume later.
        """
        run.had_failures = True
        run.consecutive_failures += 1

        if run.transcribed > 0:
            run.error = SubtitleError(
                _("Transcription stopped at {span}: {error}").format(span=SpanLabel(chunk), error=error),
                error=error)
            logging.error(str(run.error))
            return True

        if run.consecutive_failures >= _MAX_INITIAL_FAILURES:
            raise SubtitleError(
                _("Transcription blocked after {count} consecutive chunk failures: {error}").format(
                    count=run.consecutive_failures, error=error),
                error=error)

        run.error = error
        logging.warning(_("Skipping chunk {}: {}").format(SpanLabel(chunk), error))
        return False

    def _accept_chunk(self, run : _TranscriptionRun, segment : TranscriptionSegment|None,
                      provider_responded : bool) -> None:
        """Fold a successfully processed chunk into the run."""
        run.chunks_done += 1

        if provider_responded:
            # An empty provider response was successful and may follow a
            # transient backend failure. Silent chunks are skipped before a
            # request and must not reset the failure count.
            run.consecutive_failures = 0

        if segment is None:
            return

        for line in self.line_builder.LinesForSegment(segment):
            if run.AddLine(line) is not None:
                self.events.segment.send(self, segment=line)

    def _finish_run(self, run : _TranscriptionRun, media_path : str) -> TranscriptionOutcome:
        """Assemble the run's lines into Subtitles and report the outcome."""
        if run.transcribed == 0:
            return self._failed(SubtitleError(_("No timed subtitles could be produced from {}").format(media_path)))

        logging.info(_("Transcribed {} lines from {} chunks").format(run.transcribed, run.chunks_done))
        if run.total_cost > 0:
            logging.info(_("Transcription cost: ${:.4f}").format(run.total_cost))

        subtitles = Subtitles()
        subtitles.originals = run.lines
        subtitles.sourcepath = os.path.normpath(media_path)
        subtitles.file_format = '.srt'

        status = TranscriptionStatus.INCOMPLETE if run.had_failures else TranscriptionStatus.COMPLETED
        return TranscriptionOutcome(status=status, subtitles=subtitles, error=run.error,
                                    transcribed_lines=run.transcribed, total_cost=run.total_cost)

    def _process_transcription(self, subtitles : Subtitles, options : Options) -> None:
        """
        Pre- and post-process transcribed lines (dash normalization, filler
        word removal, dialog breaks, duration-based line splitting).  Works
        on the flat originals list, no batching or scenes involved.
        """
        if not subtitles.originals:
            return
        processor = SubtitleProcessor(SettingsType(options))
        lines = processor.PreprocessSubtitles(subtitles.originals)
        lines = [line for line in processor.PostprocessSubtitles(lines)
                 if line.text and line.text.strip()]
        subtitles.originals = lines

    def _transcribe_chunk(self, run : _TranscriptionRun, client : TranscriptionClient, media_path : str,
                          chunk : AudioChunk) -> tuple[TranscriptionSegment|None, bool]:
        """
        Read and transcribe one chunk. Returns the segment (None for silent
        or empty chunks) and whether the provider was actually asked.
        Backend and read errors propagate to the run loop's failure policy.
        """
        audio_bytes = self.extractor.ReadChunkBytes(media_path, chunk.start, chunk.end, self.track_index)

        if self.extractor.IsSilent(audio_bytes, self.silence_skip_db):
            logging.debug(_("Skipping silent chunk {} before requesting").format(SpanLabel(chunk)))
            return None, False

        result = client.TranscribeChunk(audio_bytes, 'wav', self.language)

        if result.cost:
            run.total_cost += result.cost

        text = (result.text or '').strip()

        if not text:
            logging.debug(_("Empty transcription for chunk {}").format(SpanLabel(chunk)))
            return None, True

        return TranscriptionSegment(start=chunk.start, end=chunk.end, text=text,
                                    language=result.language or self.language,
                                    words=result.words, parts=result.parts), True
