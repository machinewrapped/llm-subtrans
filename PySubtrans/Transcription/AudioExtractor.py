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
from collections.abc import Generator
from dataclasses import dataclass
from datetime import timedelta

from PySubtrans.Helpers.Localization import _
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.Transcription.SilenceStream import SilenceStream

SUPPORTED_MEDIA_EXTENSIONS = ('.mp4', '.mkv', '.m4a', '.mp3', '.wav', '.flac', '.ogg', '.webm', '.aac', '.mov', '.avi')
FFMPEG_TEXT_ENCODING = 'utf-8'

@dataclass
class AudioTrack:
    """
    A single audio stream in a media file.
    """
    index : int = 0
    codec : str|None = None
    language : str|None = None
    channels : int|None = None

    def __str__(self) -> str:
        """Human-readable track label."""
        parts = [f"Track {self.index}"]
        if self.codec:
            parts.append(str(self.codec))
        if self.language:
            parts.append(str(self.language))

        return " - ".join(parts)

    def __repr__(self) -> str:
        return f"AudioTrack(index={self.index}, codec={self.codec!r}, language={self.language!r}, channels={self.channels!r})"


class AudioExtractor:
    """
    Extracts normalized audio from media files using ffmpeg.

    All output is mono 16kHz PCM, the format every transcription backend
    in this project consumes. No third-party Python dependencies.
    """
    def __init__(self, settings : SettingsType|None = None):
        self.settings : SettingsType = settings or SettingsType()

        explicit_ffmpeg = _configured_ffmpeg_path(self.settings)
        self.ffmpeg_path : str = explicit_ffmpeg or 'ffmpeg'
        self.ffprobe_path : str = _ffprobe_command(self.ffmpeg_path, explicit_ffmpeg is not None)

        CheckFfmpegAvailable(self.settings)

    @property
    def sample_rate(self) -> int:
        """Target sample rate in Hz."""
        return self.settings.get_int('sample_rate') or 16000

    def GetDuration(self, media_path : str) -> timedelta:
        """
        Return the total duration of the media file.
        """
        self._check_media_path(media_path)

        output = self._run(
            [self.ffprobe_path, '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', media_path],
            timeout=60, error_message=_("Unable to probe media duration: {}"))

        try:
            return timedelta(seconds=float(output.strip()))

        except ValueError as e:
            raise SubtitleError(_("Unable to parse media duration"), error=e)

    def ListAudioTracks(self, media_path : str) -> list[AudioTrack]:
        """
        List the audio streams in a media file.
        """
        self._check_media_path(media_path)

        output = self._run(
            [self.ffprobe_path, '-v', 'error', '-select_streams', 'a',
             '-show_entries', 'stream=index,codec_name,channels:stream_tags=language',
             '-of', 'csv=p=0', media_path],
            timeout=60, error_message=_("Unable to list audio tracks: {}"))

        tracks : list[AudioTrack] = []
        for stream_index, line in enumerate(output.splitlines()):
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

        self._run(
            [self.ffmpeg_path, '-y', '-v', 'error',
             '-ss', str(start.total_seconds()), '-i', media_path,
             '-t', str(duration.total_seconds()),
             '-map', f'0:a:{track_index}',
             '-ac', '1', '-ar', str(self.sample_rate),
             '-c:a', 'pcm_s16le', output_path],
            timeout=600, error_message=_("Audio extraction failed: {}"))

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

        audio = _read_pcm16(audio_bytes)
        if audio is None:
            return False

        samples, _sample_rate = audio
        if not samples:
            return True

        peak = max(abs(sample) for sample in samples)
        if peak == 0:
            return True

        level_db = 20.0 * math.log10(peak / 32768.0)
        return level_db < threshold_db

    def QuietestStretch(self, audio_bytes : bytes, stretch_seconds : float) -> tuple[float, float]|None:
        """
        Return the (start, end) offsets in seconds of the lowest-energy stretch of chunk audio.

        Finds a pause by its level relative to the surrounding audio.
        This still works when background sound keeps the pause above a fixed noise floor.
        Ties go to the latest stretch.
        """
        audio = _read_pcm16(audio_bytes)
        if audio is None:
            return None

        # Sum energy in 10ms frames, then slide a stretch-long window over the frames
        samples, sample_rate = audio
        frame_size = max(1, sample_rate // 100)
        energies = [sum(sample * sample for sample in samples[i:i + frame_size])
                    for i in range(0, len(samples) - frame_size + 1, frame_size)]

        stretch_frames = max(1, round(stretch_seconds * 100))
        if len(energies) < stretch_frames:
            return None

        window = sum(energies[:stretch_frames])
        best_energy, best_frame = window, 0
        for frame in range(1, len(energies) - stretch_frames + 1):
            window += energies[frame + stretch_frames - 1] - energies[frame - 1]
            if window <= best_energy:
                best_energy, best_frame = window, frame

        start = best_frame * frame_size / sample_rate
        return start, start + stretch_frames * frame_size / sample_rate

    def DetectSilences(self, media_path : str, track_index : int = 0,
                       min_duration : float|None = None, noise_db : int|None = None) -> list[tuple[timedelta, timedelta]]:
        """
        Return (start, end) silence intervals using ffmpeg silencedetect.
        """
        return list(self.DetectSilencesStream(media_path, track_index, min_duration, noise_db))

    def DetectSilencesStream(self, media_path : str, track_index : int = 0,
                             min_duration : float|None = None, noise_db : int|None = None) -> Generator[tuple[timedelta, timedelta], None, None]:
        """
        Yield (start, end) silence intervals in chronological order while
        ffmpeg is still scanning, so chunk planning and transcription can
        overlap the scan instead of blocking on it.
        """
        self._check_media_path(media_path)

        min_duration = min_duration or self.settings.get_float('silence_min_duration') or 0.8
        noise_db = noise_db if noise_db is not None else self.settings.get_int('silence_noise_db') or -30

        # The scan decodes the whole audio track, but it streams events as
        # they are found, so transcription starts on the first chunk right away
        logging.info(_("Analysing audio for silences in {}").format(
            os.path.basename(media_path)))

        stream = SilenceStream(media_path, track_index, min_duration, noise_db, ffmpeg_path=self.ffmpeg_path)
        with stream:
            yield from stream

    def _run(self, args : list[str], timeout : int, error_message : str) -> str:
        """
        Run an ffmpeg or ffprobe command and return its stdout.

        A non-zero exit raises the given message with the tail of stderr filled in.
        """
        result = subprocess.run(
            args, capture_output=True, text=True, encoding=FFMPEG_TEXT_ENCODING,
            errors='replace', timeout=timeout)

        if result.returncode != 0:
            raise SubtitleError(error_message.format(result.stderr.strip()[-500:]))

        return result.stdout

    def _check_media_path(self, media_path : str) -> None:
        if not media_path or not os.path.isfile(media_path):
            raise SubtitleError(_("Media file not found: {}").format(media_path))

    def _temp_wav_path(self) -> str:
        handle, path = tempfile.mkstemp(suffix='.wav', prefix='subtrans-chunk-')
        os.close(handle)
        return path


######################################################################

def CheckFfmpegAvailable(settings : SettingsType|None = None) -> None:
    """
    Raise if the configured ffmpeg/ffprobe pair, or the system PATH pair,
    cannot be found.
    """
    ffmpeg_path = _configured_ffmpeg_path(settings)
    if ffmpeg_path is None:
        if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
            raise SubtitleError(_("ffmpeg and ffprobe are required for transcription but were not found on PATH"))
        return

    if not os.path.isfile(ffmpeg_path) or (os.name != 'nt' and not os.access(ffmpeg_path, os.X_OK)):
        raise SubtitleError(_("The configured ffmpeg executable was not found: {}").format(ffmpeg_path))

    ffprobe_path = _ffprobe_command(ffmpeg_path, explicit_ffmpeg=True)
    if ffprobe_path == 'ffprobe':
        if not shutil.which('ffprobe'):
            raise SubtitleError(_(
                "ffprobe was not found alongside the configured ffmpeg executable or on PATH"
            ))
    elif not os.path.isfile(ffprobe_path) or (os.name != 'nt' and not os.access(ffprobe_path, os.X_OK)):
        raise SubtitleError(_("The ffprobe executable paired with ffmpeg was not found: {}").format(ffprobe_path))


def _configured_ffmpeg_path(settings : SettingsType|None) -> str|None:
    """Return a normalized explicitly configured ffmpeg path, if any."""
    if settings is None:
        return None

    configured = settings.get_str('ffmpeg_path')
    if not configured or not configured.strip():
        return None

    return os.path.expanduser(os.path.expandvars(configured.strip()))


def _ffprobe_command(ffmpeg_path : str, explicit_ffmpeg : bool) -> str:
    """Choose the ffprobe paired with an explicit ffmpeg, when present."""
    if not explicit_ffmpeg:
        return 'ffprobe'

    extension = os.path.splitext(ffmpeg_path)[1]
    if extension.casefold() not in ('.exe', '.bat', '.cmd'):
        extension = ''

    candidate = os.path.join(os.path.dirname(os.path.abspath(ffmpeg_path)), f'ffprobe{extension}')
    return candidate if os.path.isfile(candidate) else 'ffprobe'


def _read_pcm16(audio_bytes : bytes) -> tuple[array.array[int], int]|None:
    """Return the samples and sample rate of 16-bit WAV audio, or None if it cannot be read."""
    try:
        with wave.open(io.BytesIO(audio_bytes), 'rb') as wav:
            frames = wav.readframes(wav.getnframes())
            width = wav.getsampwidth()
            sample_rate = wav.getframerate()

    except (wave.Error, EOFError, ValueError):
        return None

    if not frames or width != 2:
        return None

    samples = array.array('h')
    samples.frombytes(frames)
    return samples, sample_rate
