"""Escape hatch for PySide6's builtins.__import__ replacement.

PySide6 replaces builtins.__import__ with its own wrapper as soon as it is imported, to support the `from __feature__ import ...` compatibility syntax (unused by this project).
Left in place for a later import, that wrapper corrupts six's synthetic module machinery the first time pandas is imported (pulled in transitively by the optional qwen-asr package), breaking transformers with a misleading "cannot import name 'GenerationMixin'" error.

The GUI entry point captures the true, unpatched import function here before PySide6 ever loads.
Code that needs to import something through the unpatched import machinery can request it via UsingOriginalImport(); outside the GUI (nothing captured) this is a no-op, since nothing patched __import__ in the first place.
"""
import builtins
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any

_original_import : Callable[..., Any]|None = None


def CaptureOriginalImport() -> None:
    """Record the current builtins.__import__, before anything can replace it."""
    global _original_import
    _original_import = builtins.__import__


@contextmanager
def UsingOriginalImport() -> Generator[None, None, None]:
    """Temporarily swap in the captured import function, if one was captured."""
    if _original_import is None:
        yield
        return

    current_import = builtins.__import__
    builtins.__import__ = _original_import
    try:
        yield
    finally:
        builtins.__import__ = current_import
