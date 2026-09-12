from blinker import Signal


class TranscriptionEvents:
    """
    Container for blinker signals emitted during transcription.

    Mirrors TranslationEvents: subscribe before starting a run to receive
    progress feedback from the coordinator.

    Signals:
        progress(sender, done : int, total : int, span : str):
            Emitted before each chunk is transcribed. Total is 0 while the
            chunk plan is still streaming in.

        audio_progress(sender, processed : float, total : float):
            Emitted as audio seconds are processed, once the media duration
            is known.

        segment(sender, segment : TranscriptionSegment):
            Emitted for each timed subtitle line as it is produced.
    """
    progress : Signal
    audio_progress : Signal
    segment : Signal

    def __init__(self):
        self.progress = Signal("transcription-progress")
        self.audio_progress = Signal("transcription-audio-progress")
        self.segment = Signal("transcription-segment")
