from __future__ import annotations

import array
import io
import logging
import math
import os
import shutil
import subprocess
import tempfile
import wave
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta

import regex

from PySubtrans.Helpers.Localization import _
from PySubtrans.Helpers.Time import GetTimeDeltaSafe
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import SubtitleError

# Silence intervals reported by ffmpeg silencedetect, e.g.
# [silencedetect @ 0x...] silence_start: 12.34 | silence_end: 13.02 | silence_duration: 0.68
SILENCE_PATTERN = regex.compile(
    r'silence_(?P<kind>start|end):\s*(?P<time>-?\d+(?:\.\d+)?)'
)

SUPPORTED_MEDIA_EXTENSIONS = ('.mp4', '.mkv', '.m4a', '.mp3', '.wav', '.flac', '.ogg', '.webm', '.aac', '.mov', '.avi')


@dataclass
class AudioTrack:
    """
    A single audio stream in a media file.
    """
    index : int = 0
    codec : str|None = None
    language : str|None = None
    channels : int|None = None


@dataclass
class AudioChunk:
    """
    A coherent span of audio to transcribe as one unit.

    Timings are absolute offsets from the start of the source media.
    """
    start : timedelta = field(default_factory=lambda: timedelta(seconds=0))
    end : timedelta = field(default_factory=lambda: timedelta(seconds=0))
    path : str|None = None


def CheckFfmpegAvailable() -> None:
    """
    Raise if ffmpeg/ffprobe cannot be found on PATH.
    """
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise SubtitleError(_("ffmpeg and ffprobe are required for transcription but were not found on PATH"))


class AudioExtractor:
    """
    Extracts normalized audio from media files using ffmpeg.

    All output is mono 16kHz PCM, the format every transcription backend
    in this project consumes. No third-party Python dependencies.
    """
    def __init__(self, settings : SettingsType|None = None):
        self.settings : SettingsType = settings or SettingsType()
        CheckFfmpegAvailable()

    @property
    def sample_rate(self) -> int:
        """Target sample rate in Hz."""
        return self.settings.get_int('sample_rate') or 16000

    def GetDuration(self, media_path : str) -> timedelta:
        """
        Return the total duration of the media file.
        """
        self._check_media_path(media_path)
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', media_path],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            raise SubtitleError(_("Unable to probe media duration: {}").format(result.stderr.strip()))

        try:
            return timedelta(seconds=float(result.stdout.strip()))
        except ValueError as e:
            raise SubtitleError(_("Unable to parse media duration"), error=e)

    def ListAudioTracks(self, media_path : str) -> list[AudioTrack]:
        """
        List the audio streams in a media file.
        """
        self._check_media_path(media_path)
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'a',
             '-show_entries', 'stream=index,codec_name,channels:stream_tags=language',
             '-of', 'csv=p=0', media_path],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            raise SubtitleError(_("Unable to list audio tracks: {}").format(result.stderr.strip()))

        tracks : list[AudioTrack] = []
        for stream_index, line in enumerate(result.stdout.splitlines()):
            parts = [part.strip() for part in line.split(',')]
            if len(parts) < 2:
                continue
            codec = parts[1] or None
            channels = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
            language = parts[3] if len(parts) > 3 and parts[3] else None
            tracks.append(AudioTrack(index=stream_index, codec=codec, language=language, channels=channels))

        if not tracks:
            raise SubtitleError(_("No audio tracks found in {}").format(media_path))

        return tracks

    def ExtractChunk(self, media_path : str, start : timedelta, end : timedelta,
                     track_index : int = 0, output_path : str|None = None) -> str:
        """
        Extract a time span to a mono 16kHz WAV file. Returns the file path.
        """
        self._check_media_path(media_path)
        duration = end - start
        if duration.total_seconds() <= 0:
            raise SubtitleError(_("Invalid chunk time span"))

        output_path = output_path or self._temp_wav_path()
        start_seconds = start.total_seconds()

        result = subprocess.run(
            ['ffmpeg', '-y', '-v', 'error',
             '-ss', str(start_seconds), '-i', media_path,
             '-t', str(duration.total_seconds()),
             '-map', f'0:a:{track_index}',
             '-ac', '1', '-ar', str(self.sample_rate),
             '-c:a', 'pcm_s16le', output_path],
            capture_output=True, text=True, timeout=600
        )
        if result.returncode != 0:
            raise SubtitleError(_("Audio extraction failed: {}").format(result.stderr.strip()[-500:]))

        return output_path

    def ReadChunkBytes(self, media_path : str, start : timedelta, end : timedelta, track_index : int = 0) -> bytes:
        """
        Extract a time span and return the WAV bytes directly.
        """
        chunk_path = self.ExtractChunk(media_path, start, end, track_index)
        try:
            with open(chunk_path, 'rb') as f:
                return f.read()
        finally:
            try:
                os.remove(chunk_path)
            except OSError:
                pass

    def IsSilent(self, audio_bytes : bytes, threshold_db : float|None = None) -> bool:
        """
        True when chunk audio sits below an energy threshold.

        Catches near-silent chunks that slip through silence detection
        (fades, room tone) before they cost a transcription request.
        Music and noise still pass: only the engine can judge those.
        """
        threshold_db = threshold_db if threshold_db is not None else -40.0
        try:
            with wave.open(io.BytesIO(audio_bytes), 'rb') as wav:
                frames = wav.readframes(wav.getnframes())
                width = wav.getsampwidth()
        except (wave.Error, EOFError, ValueError):
            return False

        if not frames or width != 2:
            return False

        samples = array.array('h')
        samples.frombytes(frames)
        if not samples:
            return True

        peak = max(abs(sample) for sample in samples)
        if peak == 0:
            return True

        level_db = 20.0 * math.log10(peak / 32768.0)
        return level_db < threshold_db

    def DetectSilences(self, media_path : str, track_index : int = 0,
                       min_duration : float|None = None, noise_db : int|None = None) -> list[tuple[timedelta, timedelta]]:
        """
        Return (start, end) silence intervals using ffmpeg silencedetect.
        """
        self._check_media_path(media_path)
        min_duration = min_duration or self.settings.get_float('silence_min_duration') or 0.8
        noise_db = noise_db if noise_db is not None else self.settings.get_int('silence_noise_db') or -30

        result = subprocess.run(
            ['ffmpeg', '-v', 'info', '-i', media_path,
             '-map', f'0:a:{track_index}',
             '-af', f'silencedetect=noise={noise_db}dB:d={min_duration}',
             '-f', 'null', '-'],
            capture_output=True, text=True, timeout=900
        )
        # silencedetect reports to stderr and ffmpeg exits 0 regardless
        silences : list[tuple[timedelta, timedelta]] = []
        pending_start : float|None = None
        for line in result.stderr.splitlines():
            match = SILENCE_PATTERN.search(line)
            if not match:
                continue
            if match.group('kind') == 'start':
                pending_start = float(match.group('time'))
            elif pending_start is not None:
                start = GetTimeDeltaSafe(pending_start) or timedelta(seconds=max(0.0, pending_start))
                end_time = float(match.group('time'))
                end = GetTimeDeltaSafe(end_time) or timedelta(seconds=max(0.0, end_time))
                silences.append((start, end))
                pending_start = None

        return silences

    def _check_media_path(self, media_path : str) -> None:
        if not media_path or not os.path.isfile(media_path):
            raise SubtitleError(_("Media file not found: {}").format(media_path))

    def _temp_wav_path(self) -> str:
        handle, path = tempfile.mkstemp(suffix='.wav', prefix='subtrans-chunk-')
        os.close(handle)
        return path


class AudioChunker:
    """
    Splits media into coherent audio-only chunks for transcription.

    Cuts land inside detected silence where possible so chunks hold
    complete utterances (better for both accuracy and speaker continuity).
    A hard cap guarantees no chunk exceeds backend length limits.
    Chunks never overlap: each engine returns flat text per chunk, so
    overlap would transcribe the same speech twice.
    """
    def __init__(self, settings : SettingsType|None = None):
        self.settings : SettingsType = settings or SettingsType()
        self.extractor : AudioExtractor = AudioExtractor(self.settings)

    @property
    def min_chunk_seconds(self) -> float:
        """Minimum chunk length; shorter spans merge into neighbours."""
        return self.settings.get_float('min_chunk_seconds') or 4.0

    @property
    def max_chunk_seconds(self) -> float:
        """
        Hard cap per chunk. The local engine returns flat text per chunk
        with no word timings, so chunk boundaries ARE the subtitle timings:
        keep the cap low enough that worst-case lines stay usable.
        """
        return self.settings.get_float('max_chunk_seconds') or 60.0

    @property
    def lookahead_seconds(self) -> float:
        """
        How far past the cap to scan for a silence before hard-cutting.

        Hard cuts can land mid-sentence or mid-word, so an over-long
        stretch extends to the next natural pause when one is nearby.
        """
        return self.settings.get_float('lookahead_seconds') or 30.0

    def PlanChunks(self, media_path : str, track_index : int = 0,
                   progress_cb : Callable[[str], None]|None = None) -> list[AudioChunk]:
        """
        Return the ordered chunk plan for a media file (no audio extracted yet).
        """
        duration = self.extractor.GetDuration(media_path)
        total = duration.total_seconds()
        if total <= 0:
            raise SubtitleError(_("Media file has no playable duration"))

        if progress_cb:
            progress_cb(_("Detecting silence in {}").format(os.path.basename(media_path)))

        silences = self.extractor.DetectSilences(media_path, track_index)

        chunks : list[AudioChunk] = []
        cursor = timedelta(seconds=0)
        silence_index = 0

        while (duration - cursor).total_seconds() >= self.min_chunk_seconds:
            target = cursor + timedelta(seconds=self.max_chunk_seconds)
            window = min(target, duration)

            # Next natural cut within the cap (or the file end)
            cut = self._next_silence_cut(silences, silence_index, cursor, window)
            if cut is not None:
                silence_index = cut[1]
                end = duration if cut[0] >= duration else cut[0]
                chunks.append(AudioChunk(start=cursor, end=end))
                cursor = duration if end >= duration else self._silence_end_after(silences, silence_index - 1, cut[0])
                continue

            if target >= duration:
                chunks.append(AudioChunk(start=cursor, end=duration))
                cursor = duration
                break

            # Over-long stretch: extend to a nearby silence instead of
            # cutting mid-sentence, hard-cutting only past the ceiling
            extended = self._next_silence_cut(
                silences, silence_index, cursor,
                target + timedelta(seconds=self.lookahead_seconds), after=target)
            if extended is not None:
                silence_index = extended[1]
                chunks.append(AudioChunk(start=cursor, end=extended[0]))
                cursor = self._silence_end_after(silences, silence_index - 1, extended[0])
                continue

            chunks.append(AudioChunk(start=cursor, end=target))
            cursor = target

        if chunks and (duration - cursor).total_seconds() > 0:
            # Absorb a tiny tail into the last chunk rather than dropping speech
            chunks[-1].end = duration
        elif not chunks:
            chunks.append(AudioChunk(start=timedelta(seconds=0), end=duration))

        logging.info(_("Planned {} transcription chunks for {}").format(len(chunks), os.path.basename(media_path)))
        return chunks

    def _next_silence_cut(self, silences : list[tuple[timedelta, timedelta]], index : int,
                           cursor : timedelta, limit : timedelta,
                           after : timedelta|None = None) -> tuple[timedelta, int]|None:
        """
        Score candidate silences within (after, limit] by position times
        gap length, returning the cut point and the index to resume from.
        A long pause earlier beats a short one nearer the cap, so chunks
        break on coherent boundaries instead of arbitrary times; position
        still counts, so dialogue fills toward the cap (fewer requests,
        stable speaker identities for diarization). Latest wins ties.
        Spans below the minimum length are passed over as cut candidates —
        their audio stays inside the surrounding chunk, so no speech is
        ever dropped; only the cut point moves later.
        """
        lower = after or cursor
        best : tuple[timedelta, int]|None = None
        best_score = -1.0
        while index < len(silences):
            silence_start, silence_end = silences[index]
            if silence_start <= cursor:
                index += 1
                continue
            if silence_start > limit:
                break
            span = (silence_start - cursor).total_seconds()
            if silence_start > lower and span >= self.min_chunk_seconds:
                gap = (silence_end - silence_start).total_seconds()
                score = span * gap
                if score >= best_score:
                    best_score = score
                    best = (silence_start, index + 1)
            index += 1

        return best

    def _silence_end_after(self, silences : list[tuple[timedelta, timedelta]], index : int, cut : timedelta) -> timedelta:
        """
        Resume the next chunk after the silence that was cut on, so pauses
        are not transcribed as leading dead air.
        """
        if 0 <= index < len(silences):
            silence_start, silence_end = silences[index]
            if silence_start <= cut <= silence_end and silence_end > cut:
                return silence_end

        return cut
