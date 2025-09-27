from blinker import Signal


class TranslationEvents:
    """Container for blinker signals emitted during translation."""

    preprocessed: Signal
    batch_translated: Signal
    batch_updated: Signal
    scene_translated: Signal

    def __init__(self):
        self.preprocessed = Signal("translation-preprocessed")
        self.batch_translated = Signal("translation-batch-translated")
        self.batch_updated = Signal("translation-batch-updated")
        self.scene_translated = Signal("translation-scene-translated")

