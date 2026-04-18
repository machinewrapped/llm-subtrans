import logging
from blinker import Signal
from typing import Protocol


class LoggerProtocol(Protocol):
    """Protocol for objects that can be used as loggers"""
    def error(self, msg : object, *args, **kwargs) -> None: ...
    def warning(self, msg : object, *args, **kwargs) -> None: ...
    def info(self, msg : object, *args, **kwargs) -> None: ...


class TranslationEvents:
    """
    Container for blinker signals emitted during translation.

    Subscribe to events to receive notifications from long-running translation tasks,
    e.g. to provide progress feedback or UI updates.

    Signals:
        batch_translated(sender, batch):
            Emitted after each batch is translated

        batch_updated(sender, batch):
            Emitted after each batch is updated in the subtitle project

        scene_translated(sender, scene):
            Emitted when a complete scene has been translated

        terminology_updated(sender, scene, batch, returned_terms, new_terms, conflict_terms, terminology_map):
            Emitted after a batch when the model returns a <terminology> block.
            - scene: the scene containing the batch that produced the terminology update
            - batch: the specific batch that produced the terminology update
            - returned_terms: all terms the model emitted (dict[str, str])
            - new_terms: terms added to the map for the first time (dict[str, str])
            - conflict_terms: terms already in the map that the model tried to retranslate differently (dict[str, tuple[str, str]] — original -> (existing, proposed))
            - terminology_map: the full accumulated map after this batch (dict[str, str])

        preprocessed(sender, scenes):
            Emitted after subtitles are batched and pre-processed (GuiSubtrans only)

        error(sender, message):
            Signals that an error was encountered during translation

        warning(sender, message):
            Signals that a warning was encountered during translation

        info(sender, message):
            General informational message during translation
    """
    preprocessed: Signal
    batch_translated: Signal
    batch_updated: Signal
    scene_translated: Signal
    terminology_updated: Signal
    error: Signal
    warning: Signal
    info: Signal

    def __init__(self):
        self.preprocessed = Signal("translation-preprocessed")
        self.batch_translated = Signal("translation-batch-translated")
        self.batch_updated = Signal("translation-batch-updated")
        self.scene_translated = Signal("translation-scene-translated")
        self.terminology_updated = Signal("translation-terminology-updated")

        # Signals for logging translation events
        self.error = Signal("translation-error")
        self.warning = Signal("translation-warning")
        self.info = Signal("translation-info")

        # Wrapper functions to adapt signal kwargs to logger positional args
        self._default_error_wrapper = lambda sender, message: logging.error(message)
        self._default_warning_wrapper = lambda sender, message: logging.warning(message)
        self._default_info_wrapper = lambda sender, message: logging.info(message)

    def connect_default_loggers(self):
        """
        Connect default logging handlers to logging signals.
        """
        self.error.connect(self._default_error_wrapper, weak=False)
        self.warning.connect(self._default_warning_wrapper, weak=False)
        self.info.connect(self._default_info_wrapper, weak=False)

    def disconnect_default_loggers(self):
        """
        Disconnect default logging handlers from the signals.
        """
        self.error.disconnect(self._default_error_wrapper)
        self.warning.disconnect(self._default_warning_wrapper)
        self.info.disconnect(self._default_info_wrapper)

    def connect_logger(self, logger : LoggerProtocol):
        """
        Connect a custom logger to the logging signals.

        Args:
            logger: A logger-like object with error, warning, and info methods
        """
        # Create wrapper functions to adapt signal kwargs to logger positional args
        def error_wrapper(sender, message):
            logger.error(message)

        def warning_wrapper(sender, message):
            logger.warning(message)

        def info_wrapper(sender, message):
            logger.info(message)

        # Use weak=False to prevent garbage collection of closures
        self.error.connect(error_wrapper, weak=False)
        self.warning.connect(warning_wrapper, weak=False)
        self.info.connect(info_wrapper, weak=False)
