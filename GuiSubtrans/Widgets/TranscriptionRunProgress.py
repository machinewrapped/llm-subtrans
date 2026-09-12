import time
from datetime import timedelta

from PySubtrans.Helpers.Localization import _
from PySubtrans.Helpers.Time import TimedeltaToText


def _format_duration(seconds : float) -> str:
    """
    Format an elapsed-time estimate as m:ss.
    """
    total = max(0, int(seconds))
    return f"{total // 60}:{total % 60:02d}"


def _format_timestamp(seconds : float) -> str:
    """
    Format an audio position using the project's standard timestamp format.
    """
    timestamp = TimedeltaToText(timedelta(seconds=max(0.0, seconds)), include_milliseconds=False)
    return timestamp if ':' in timestamp else f"0:{timestamp}"


def _format_span(span : str) -> str:
    """
    Convert a coordinator span from raw seconds to readable timestamps.
    """
    start_text, separator, end_text = span.partition('-')
    if not separator or not start_text.endswith('s') or not end_text.endswith('s'):
        return span
    try:
        start = float(start_text[:-1])
        end = float(end_text[:-1])
    except ValueError:
        return span
    return f"{_format_timestamp(start)}-{_format_timestamp(end)}"


class TranscriptionRunProgress:
    """
    Position and timing bookkeeping for one transcription run, rendered
    as the dialog's status line (chunk position, span, elapsed and ETA).
    """
    # Elapsed time before an ETA is shown, and the minimum audio fraction it needs
    ETA_MIN_ELAPSED : float = 5.0
    ETA_MIN_FRACTION : float = 0.02

    def __init__(self):
        self.started : float = 0.0
        self.chunks_done : int = 0
        self.chunks_total : int = 0
        self.audio_done : float = 0.0
        self.audio_total : float = 0.0
        self.last_span : str = ""

    @property
    def elapsed(self) -> float:
        return max(0.0, time.monotonic() - self.started) if self.started else 0.0

    def Reset(self) -> None:
        """Start timing a fresh run from the beginning."""
        self.chunks_done = 0
        self.chunks_total = 0
        self.audio_done = 0.0
        self.audio_total = 0.0
        self.last_span = ""
        self.started = time.monotonic()

    def Restart(self) -> None:
        """Restart timing for a resumed run, keeping the positions reached."""
        self.started = time.monotonic()

    def OnProgress(self, done : int, total : int, span : str) -> None:
        self.chunks_done = done
        self.chunks_total = total
        self.last_span = span

    def OnAudioProgress(self, processed : float, total : float) -> None:
        self.audio_done = max(0.0, processed)
        self.audio_total = max(0.0, total)

    def StatusText(self) -> str:
        """Meaningful run status: position, current span, elapsed time and ETA."""
        if self.chunks_total > 0:
            status = _("Transcribing chunk {current}/{total}").format(
                current=min(self.chunks_done + 1, self.chunks_total), total=self.chunks_total)
        else:
            status = _("Transcribing chunk {current}").format(current=self.chunks_done + 1)

        if self.last_span:
            status += f" [{_format_span(self.last_span)}"
            if self.audio_total > 0.0:
                status += _(" of {}").format(_format_timestamp(self.audio_total))
            status += "]"
        elif self.audio_total > 0.0:
            status += _(" (source length {})").format(_format_timestamp(self.audio_total))

        elapsed = self.elapsed
        status += _(" (elapsed {})").format(_format_duration(elapsed))
        remaining = self._estimate_remaining(elapsed)
        if remaining is not None:
            status += _(" (about {} left)").format(_format_duration(remaining))
        return status

    def _estimate_remaining(self, elapsed : float) -> float|None:
        """Extrapolate remaining time from audio progress once the run has settled."""
        if elapsed <= self.ETA_MIN_ELAPSED or self.audio_total <= 0.0 or self.audio_done <= 0.0:
            return None
        fraction = min(1.0, self.audio_done / self.audio_total)
        if fraction <= self.ETA_MIN_FRACTION:
            return None
        return elapsed / fraction - elapsed
