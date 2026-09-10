from __future__ import annotations

import logging
import os
from collections.abc import Callable, Generator
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
from PySubtrans.Transcription.TranscriptionLines import SpanLabel, TranscriptionLineBuilder
from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionSegment


class TranscriptionStatus(str, Enum):
    """State of the most recent transcription run."""
    IDLE = "idle"
    COMPLETED = "completed"
    INCOMPLETE = "incomplete"
    FAILED = "failed"


# Signature for transcription progress callbacks: (chunks_completed, chunk_total, current_chunk_span)
TranscriptionProgressCallback = Callable[[int, int, str], None]
# Signature for audio progress callbacks: (audio_seconds_processed, total_audio_seconds)
TranscriptionAudioProgressCallback = Callable[[float, float], None]
# Signature for per-chunk callbacks: invoked with each transcribed segment
TranscriptionSegmentCallback = Callable[[TranscriptionSegment], None]

# Consecutive chunk failures before an empty run is treated as blocked
_MAX_INITIAL_FAILURES = 2


class _TranscriptionRun:
    """
    Mutable state for one TranscribeMedia call: accumulated lines,
    resume position and failure bookkeeping.
    """
    def __init__(self, prior_subtitles : Subtitles|None):
        self.lines : list[SubtitleLine] = []
        self.line_number : int = 0
        self.resume_after : timedelta|None = None
        self.transcribed : int = 0
        self.chunks_done : int = 0
        self.consecutive_failures : int = 0
        self.had_failures : bool = False
        self.incomplete_error : SubtitleError|None = None
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
            self.max_line_chars, self.max_line_seconds, self.word_gap_split)

        self._active_client : TranscriptionClient|None = None
        self.total_cost : float = 0.0
        self.transcribed_lines : int = 0
        self.status : TranscriptionStatus = TranscriptionStatus.IDLE
        self.last_error : SubtitleError|None = None
        self.partial_subtitles : Subtitles|None = None

    @property
    def track_index(self) -> int:
        """Audio track to transcribe (0-based within audio streams)."""
        return self.settings.get_int('audio_track') or 0

    @property
    def language(self) -> str|None:
        """Spoken language hint for the transcription engine."""
        return self.settings.get_str('language') or self.provider.settings.get_str('language')

    @property
    def max_line_chars(self) -> int:
        """Maximum characters per subtitle line when grouping aligned words."""
        return self.settings.get_int('transcription_max_chars') or 84

    @property
    def max_line_seconds(self) -> float:
        """Maximum duration per subtitle line when grouping aligned words."""
        return self.settings.get_float('transcription_max_line_seconds') or 8.0

    @property
    def word_gap_split(self) -> float:
        """Inter-word pause that forces a new subtitle line, in seconds."""
        return self.settings.get_float('transcription_gap_split') or 0.5

    @property
    def silence_skip_db(self) -> float:
        """Peak level below which chunks skip transcription entirely."""
        return self.settings.get_float('silence_skip_db') or -40.0

    @classmethod
    def ResolveProviderSettings(cls, provider_name : str, settings : SettingsType,
                                provider_settings : SettingsType|None = None) -> SettingsType:
        """
        Merge settings with shared credentials from the provider_settings dict.

        Only credentials travel across capabilities (api_key, proxy): endpoint
        conventions differ per capability (translation and transcription use
        different base paths), so server addresses and models are never
        shared. Transcription settings live under "<name> Transcription".
        """
        resolved = SettingsType(settings or {})
        if provider_settings is not None:
            # Transcription-specific settings fill gaps; explicit settings win.
            own = provider_settings.get_dict(cls.SettingsKey(provider_name))
            if own:
                resolved = SettingsType(own | resolved)

            # Only credentials travel across capabilities, never endpoints.
            shared = provider_settings.get_dict(provider_name)
            for key in ('api_key', 'proxy'):
                if not resolved.get(key) and shared.get(key):
                    resolved[key] = shared.get(key)

        return resolved

    @staticmethod
    def SettingsKey(provider_name : str) -> str:
        """
        Settings namespace for a transcription provider, kept separate
        from its translation counterpart (see ResolveProviderSettings).
        """
        return f"{provider_name} Transcription"

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

    def TranscribeMedia(self, media_path : str, progress_cb : TranscriptionProgressCallback|None = None,
                        segment_cb : TranscriptionSegmentCallback|None = None,
                        audio_progress_cb : TranscriptionAudioProgressCallback|None = None,
                        prior_subtitles : Subtitles|None = None) -> Subtitles:
        """
        Transcribe a media file into timestamped subtitles.

        When *prior_subtitles* is supplied (from an earlier aborted run),
        already-transcribed chunks are skipped and the new lines are appended
        after the existing ones.
        """
        self._reset_state()
        if not media_path or not os.path.isfile(media_path):
            self.status = TranscriptionStatus.FAILED
            raise SubtitleError(_("Media file not found: {}").format(media_path))

        client = self._start_client()
        run = _TranscriptionRun(prior_subtitles)

        def on_duration(duration : timedelta) -> None:
            run.audio_total_seconds = max(0.0, duration.total_seconds())
            if audio_progress_cb and run.audio_total_seconds > 0.0:
                audio_progress_cb(0.0, run.audio_total_seconds)

        chunks = self.chunker.PlanChunksStream(media_path, self.track_index, duration_cb=on_duration)
        logging.info(_("Transcribing {} with {} (chunks stream in while silence detection runs)").format(
            os.path.basename(media_path), self.provider.name))

        try:
            self._run_chunks(run, client, media_path, chunks, progress_cb, segment_cb, audio_progress_cb)
        except SubtitleError as e:
            # A silence-scan failure mid-run must not discard already
            # transcribed (billed) chunks.
            if run.transcribed == 0:
                raise
            run.had_failures = True
            self.last_error = e
            logging.error(str(e))
        finally:
            chunks.close()
            self._active_client = None

        return self._finish_run(run, media_path)

    def CreateTranscription(self, media_path : str, options : Options|None = None,
                            progress_cb : TranscriptionProgressCallback|None = None,
                            segment_cb : TranscriptionSegmentCallback|None = None,
                            audio_progress_cb : TranscriptionAudioProgressCallback|None = None,
                            prior_subtitles : Subtitles|None = None) -> Subtitles:
        """Transcribe media and return post-processed subtitles."""
        subtitles = self.TranscribeMedia(media_path, progress_cb, segment_cb, audio_progress_cb,
                                         prior_subtitles=prior_subtitles)

        if options is not None and options.get_bool('postprocess_transcription', True):
            self._process_transcription(subtitles, options)

        return subtitles

    def Abort(self) -> None:
        """Stop transcription after the current chunk."""
        self.aborted = True
        if self._active_client is not None:
            self._active_client.AbortTranscription()

    def _reset_state(self) -> None:
        self.status = TranscriptionStatus.IDLE
        self.last_error = None
        self.partial_subtitles = None
        self.total_cost = 0.0

    def _start_client(self) -> TranscriptionClient:
        """
        Obtain the provider client, refusing engines that cannot time their output.
        """
        client = self.provider.GetTranscriptionClient(self.settings)
        self._active_client = client
        if not client.supports_timestamps:
            self.status = TranscriptionStatus.FAILED
            raise SubtitleError(_(
                "'{}' cannot provide subtitle timings (no word or segment "
                "timestamps). Transcription without timings has no value "
                "here, so nothing was requested and no credits were spent."
            ).format(self.provider.name))
        return client

    def _run_chunks(self, run : _TranscriptionRun, client : TranscriptionClient, media_path : str,
                    chunks : Generator[AudioChunk, None, None],
                    progress_cb : TranscriptionProgressCallback|None,
                    segment_cb : TranscriptionSegmentCallback|None,
                    audio_progress_cb : TranscriptionAudioProgressCallback|None) -> None:
        """
        Transcribe each planned chunk in turn, honouring abort, resume and
        the failure policy. Partial results stay in run.lines.
        """
        def report_progress(done : int, chunk : AudioChunk) -> None:
            if progress_cb:
                # Total is unknown while the plan streams in (0 signals that)
                progress_cb(done, 0, SpanLabel(chunk))

        def report_audio(chunk : AudioChunk) -> None:
            if audio_progress_cb and run.audio_total_seconds > 0.0:
                audio_progress_cb(run.AudioPosition(chunk), run.audio_total_seconds)

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
                segment, provider_responded = self._transcribe_chunk(client, media_path, chunk)
            except SubtitleError as e:
                if self._handle_chunk_failure(run, chunk, e):
                    break
            else:
                self._accept_chunk(run, segment, provider_responded, segment_cb)
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
        self.last_error = error

        if run.transcribed > 0:
            run.incomplete_error = SubtitleError(
                _("Transcription stopped at {span}: {error}").format(span=SpanLabel(chunk), error=error),
                error=error)
            logging.error(str(run.incomplete_error))
            return True

        if run.consecutive_failures >= _MAX_INITIAL_FAILURES:
            self.status = TranscriptionStatus.FAILED
            raise SubtitleError(
                _("Transcription blocked after {count} consecutive chunk failures: {error}").format(
                    count=run.consecutive_failures, error=error),
                error=error)

        logging.warning(_("Skipping chunk {}: {}").format(SpanLabel(chunk), error))
        return False

    def _accept_chunk(self, run : _TranscriptionRun, segment : TranscriptionSegment|None,
                      provider_responded : bool, segment_cb : TranscriptionSegmentCallback|None) -> None:
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
            if run.AddLine(line) is not None and segment_cb:
                segment_cb(line)

    def _finish_run(self, run : _TranscriptionRun, media_path : str) -> Subtitles:
        """Assemble the run's lines into Subtitles and record the final status."""
        if run.transcribed == 0:
            self.status = TranscriptionStatus.FAILED
            raise SubtitleError(_("No timed subtitles could be produced from {}").format(media_path))

        self.transcribed_lines = run.transcribed
        logging.info(_("Transcribed {} lines from {} chunks").format(run.transcribed, run.chunks_done))
        if self.total_cost > 0:
            logging.info(_("Transcription cost: ${:.4f}").format(self.total_cost))

        subtitles = Subtitles()
        subtitles.originals = run.lines
        subtitles.sourcepath = os.path.normpath(media_path)
        subtitles.file_format = '.srt'
        self.partial_subtitles = subtitles

        if run.incomplete_error is not None:
            self.last_error = run.incomplete_error
        self.status = (TranscriptionStatus.INCOMPLETE if run.had_failures
                       else TranscriptionStatus.COMPLETED)
        return subtitles

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

    def _transcribe_chunk(self, client : TranscriptionClient, media_path : str,
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
            self.total_cost += result.cost

        text = (result.text or '').strip()

        if not text:
            logging.debug(_("Empty transcription for chunk {}").format(SpanLabel(chunk)))
            return None, True

        return TranscriptionSegment(start=chunk.start, end=chunk.end, text=text,
                                    language=result.language or self.language,
                                    words=result.words, parts=result.parts), True
