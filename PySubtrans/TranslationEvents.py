from blinker import Signal


class TranslationEvents:
    """Container for blinker signals emitted during translation."""

    preprocessed: Signal
    batch_translated: Signal
    scene_translated: Signal

    def __init__(self):
        self.preprocessed = Signal("translation-preprocessed")
        self.batch_translated = Signal("translation-batch-translated")
        self.scene_translated = Signal("translation-scene-translated")

