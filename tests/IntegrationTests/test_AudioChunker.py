import array
import math
import os
import shutil
import subprocess
import tempfile
import unittest
import wave
from datetime import timedelta
from unittest.mock import patch

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.SettingsType import SettingsType
from PySubtrans.Transcription.AudioExtractor import AudioChunker

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

@unittest.skipUnless(_ffmpeg_available(), "ffmpeg and ffprobe are required")
class TestAudioChunkerIntegration(LoggedTestCase):
    def test_plan_scenes_on_synthetic_audio(self):
        """Silence in the middle of audio produces two coherent chunks."""

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

    def test_stream_plan_matches_batch_plan(self):
        """Streaming planning reproduces the batch plan exactly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wav_path = os.path.join(tmpdir, "dialogue.wav")
            _make_dialogue_wav(wav_path, repeats=24)

            chunker = AudioChunker(SettingsType({'min_chunk_seconds': 8.0, 'max_chunk_seconds': 60.0}))
            batch_chunks = chunker.PlanChunks(wav_path)
            silences = chunker.extractor.DetectSilences(wav_path)

            def replay():
                for silence in silences:
                    yield silence

            with patch.object(chunker.extractor, "DetectSilencesStream", return_value=replay()):
                stream_chunks = list(chunker.PlanChunksStream(wav_path))

        self.assertLoggedEqual("chunk count", len(batch_chunks), len(stream_chunks))
        for batch_chunk, stream_chunk in zip(batch_chunks, stream_chunks):
            self.assertLoggedEqual("chunk start", batch_chunk.start, stream_chunk.start)
            self.assertLoggedEqual("chunk end", batch_chunk.end, stream_chunk.end)
