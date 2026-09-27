from __future__ import annotations

import logging
import os
import queue
import regex
import subprocess
import threading

from collections.abc import Iterator
from datetime import timedelta

from PySubtrans.Helpers.Localization import _
from PySubtrans.SubtitleError import SubtitleError


# Silence intervals reported by ffmpeg silencedetect, e.g.
# [silencedetect @ 0x...] silence_start: 12.34 | silence_end: 13.02 | silence_duration: 0.68
FFMPEG_TEXT_ENCODING = 'utf-8'
SILENCE_PATTERN = regex.compile(
    r'silence_(?P<kind>start|end):\s*(?P<time>-?\d+(?:\.\d+)?)'
)

class SilenceStream:
    """
    Streams silence intervals from ffmpeg silencedetect while ffmpeg decodes.

    A background reader thread parses stderr into a queue, so the scan keeps
    running while the consumer transcribes finalized chunks and ffmpeg never
    blocks on a full pipe. Events arrive in chronological order; use as a
    context manager so ffmpeg is terminated if the consumer stops early.
    """
    def __init__(self, media_path : str, track_index : int = 0,
                 min_duration : float = 0.8, noise_db : int = -30,
                 timeout : float = 900.0, ffmpeg_path : str = 'ffmpeg'):
        self.media_path : str = media_path
        self.track_index : int = track_index
        self.min_duration : float = min_duration
        self.noise_db : int = noise_db
        self.timeout : float = timeout
        self.ffmpeg_path : str = ffmpeg_path

        # The reader ends the queue with a terminal item: the failure that
        # stopped it, or None if ffmpeg finished cleanly
        self._events : queue.Queue[tuple[timedelta, timedelta]|SubtitleError|None] = queue.Queue()
        self._thread : threading.Thread|None = None
        self._process : subprocess.Popen[str]|None = None

    def __enter__(self) -> SilenceStream:
        if not self.media_path or not os.path.isfile(self.media_path):
            raise SubtitleError(_("Media file not found: {}").format(self.media_path))

        self._process = subprocess.Popen(
            [self.ffmpeg_path, '-v', 'info', '-i', self.media_path,
             '-map', f'0:a:{self.track_index}',
             '-af', f'silencedetect=noise={self.noise_db}dB:d={self.min_duration}',
             '-f', 'null', '-'],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
            encoding=FFMPEG_TEXT_ENCODING, errors='replace')

        self._thread = threading.Thread(target=self._read_output, daemon=True)
        self._thread.start()

        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self._shutdown()

    def __iter__(self) -> Iterator[tuple[timedelta, timedelta]]:
        if self._process is None or self._thread is None:
            raise SubtitleError(_("Silence stream was used outside a with block"))

        while True:
            # Per-wait timeout so pauses between iterations (e.g. the consumer
            # transcribing a chunk) do not count against the deadline.
            try:
                event = self._events.get(timeout=self.timeout)

            except queue.Empty:
                self._shutdown()
                raise SubtitleError(_("Silence detection timed out after {} seconds").format(int(self.timeout)))

            if event is None:
                return

            if isinstance(event, SubtitleError):
                raise event

            yield event

    def _read_output(self) -> None:
        """Reader thread: parse silencedetect lines until ffmpeg exits."""
        process = self._process
        assert process is not None and process.stderr is not None

        pending_start : float|None = None
        error : SubtitleError|None = None

        try:
            for line in process.stderr:
                match = SILENCE_PATTERN.search(line)
                if not match:
                    continue

                if match.group('kind') == 'start':
                    pending_start = float(match.group('time'))

                elif pending_start is not None:
                    end_time = float(match.group('time'))
                    self._events.put((
                        timedelta(seconds=max(0.0, pending_start)),
                        timedelta(seconds=max(0.0, end_time))))
                    pending_start = None

        except Exception as e:
            error = SubtitleError(_("Silence detection failed"), error=e)

        finally:
            # The reader owns the pipe, so it closes it once iteration has stopped
            process.stderr.close()

            returncode = process.wait()
            if returncode != 0 and error is None:
                logging.debug("ffmpeg silencedetect exited with code {}".format(returncode))

            self._events.put(error)

    def _shutdown(self) -> None:
        """Stop ffmpeg and the reader thread (safe to call repeatedly)."""
        process = self._process
        if process is not None and process.poll() is None:
            process.terminate()

        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5.0)

        if process is not None:
            try:
                process.wait(timeout=5.0)

            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()