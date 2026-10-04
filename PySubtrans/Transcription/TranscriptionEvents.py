from blinker import Signal


class TranscriptionEvents:
    """
    Container for blinker signals emitted during transcription.

    Mirrors TranslationEvents: subscribe before starting a run to receive
    progress feedback from the coordinator.

    Signals:
        status(sender, text : str):
            Emitted when the coordinator enters a new phase (preparing
            the runtime, scanning audio, etc.).

        progress(sender, done : int, span : str):
            Emitted before each chunk is transcribed.
            The chunk plan streams in during transcription, so the number of chunks is not known in advance.

        audio_progress(sender, processed : float, total : float):
            Emitted as audio seconds are processed, once the media duration
            is known.

        segment(sender, segment : TranscriptionSegment):
            Emitted for each timed subtitle line as it is produced.
    """
    status : Signal
    progress : Signal
    audio_progress : Signal
    segment : Signal

    def __init__(self):
        self.status = Signal("transcription-status")
        self.progress = Signal("transcription-progress")
        self.audio_progress = Signal("transcription-audio-progress")
        self.segment = Signal("transcription-segment")
