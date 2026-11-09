from datetime import timedelta

from PySubtrans.Transcription.AudioChunker import AudioChunk
from PySubtrans.Transcription.LineSettings import LineSettings
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionResult, TranscriptionSegment


class StreamedChunk:
    """
    Groups the parts a client streams for one chunk into segments that can become lines before the chunk is finished.

    Parts are released once a pause follows them that no line can merge across or be extended into.
    Their lines are then the same as if the whole chunk had been transcribed first.
    Streamed parts carry their own timing, so word timings are not divided between released segments.
    """
    def __init__(self, chunk : AudioChunk, settings : LineSettings, language : str|None):
        self.chunk : AudioChunk = chunk
        self.language : str|None = language
        self.released : int = 0

        # A pause at least this long ends any run of lines that could be merged
        self._release_gap : timedelta = timedelta(seconds=max(
            settings.merge_eligible_gap, settings.same_speaker_merge_eligible_gap, settings.min_gap))
        self._min_gap : timedelta = timedelta(seconds=settings.min_gap)
        self._pending : list[TranscriptionSegment] = []

    def Add(self, part : TranscriptionSegment) -> TranscriptionSegment|None:
        """Add a streamed chunk-relative part, returning a segment of the parts before it if it releases them."""
        if self._pending and part.start - max(pending.end for pending in self._pending) >= self._release_gap:
            # Lines are extended no further than the next line allows, as they would be with the whole chunk
            segment = self._Segment(self._pending, self.chunk.start + part.start - self._min_gap)
            self.released += len(self._pending)
            self._pending = [part]
            return segment

        self._pending.append(part)
        return None

    def Remainder(self, result : TranscriptionResult) -> TranscriptionSegment|None:
        """The rest of the chunk once the client returns its result, or None if every part was released."""
        if self.released == 0:
            text = (result.text or '').strip()
            if not text:
                return None

            return TranscriptionSegment(start=self.chunk.start, end=self.chunk.end, text=text,
                                        language=result.language or self.language,
                                        words=result.words, parts=result.parts)

        parts = result.parts[self.released:]
        return self._Segment(parts, self.chunk.end, result.language) if parts else None

    def _Segment(self, parts : list[TranscriptionSegment], end : timedelta, language : str|None = None) -> TranscriptionSegment:
        """A segment from the chunk start, so its parts stay relative to the chunk."""
        return TranscriptionSegment(start=self.chunk.start, end=end, text='\n'.join(part.text for part in parts),
                                    language=language or self.language, parts=list(parts))
