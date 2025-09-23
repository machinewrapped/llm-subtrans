from events import Events # type: ignore
from typing import Any, Protocol

class EventProtocol(Protocol):
    """Protocol for event objects that support both += and function calls"""
    def __call__(self, *args: Any) -> None: ...
    def __iadd__(self, handler: Any) -> 'EventProtocol': ...
    def __isub__(self, handler: Any) -> 'EventProtocol': ...

class TranslationEvents(Events):
    __events__ = ( "preprocessed", "batch_translated", "scene_translated" )

    # Type annotations for dynamic event attributes created by Events base class
    preprocessed: EventProtocol
    batch_translated: EventProtocol
    scene_translated: EventProtocol

