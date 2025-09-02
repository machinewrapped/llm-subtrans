import importlib
import inspect
import os
import pkgutil
from pathlib import Path

from PySubtitle.Helpers.Localization import _
from PySubtitle.SubtitleFileHandler import SubtitleFileHandler


class SubtitleFormatRegistry:
    """Manages discovery and lookup of subtitle file handlers."""

    _handlers : dict[str, type[SubtitleFileHandler]] = {}
    _priorities : dict[str, int] = {}
    _discovered : bool = False

    @classmethod
    def register_handler(cls, handler_class : type[SubtitleFileHandler]) -> None:
        instance = handler_class()
        priorities = instance.get_extension_priorities()
        for ext, priority in priorities.items():
            ext = ext.lower()
            if ext not in cls._handlers or priority >= cls._priorities[ext]:
                cls._handlers[ext] = handler_class
                cls._priorities[ext] = priority

    @classmethod
    def get_handler_by_extension(cls, extension : str) -> type[SubtitleFileHandler]:
        cls._ensure_discovered()
        ext = extension.lower()
        if ext not in cls._handlers:
            raise ValueError(_("Unknown subtitle format: {extension}. Available formats: {available}").format(extension=extension, available=cls.list_available_formats()))
        return cls._handlers[ext]

    @classmethod
    def create_handler(cls, extension: str|None = None, filename: str|None = None) -> SubtitleFileHandler:
        """Instantiate a subtitle file handler for the given extension."""
        if extension is None and filename is not None:
            extension = os.path.splitext(filename)[1].lower()

        if extension is None or not extension:
            raise ValueError(
                _("Format cannot be deduced from filename or extension '{name}'. Available formats: {formats}").format(
                    name=filename or extension or "None", formats=cls.list_available_formats()))

        handler_cls = cls.get_handler_by_extension(extension)
        return handler_cls()

    @classmethod
    def enumerate_formats(cls) -> list[str]:
        cls._ensure_discovered()
        return sorted(cls._handlers.keys())

    @classmethod
    def list_available_formats(cls) -> str:
        formats = cls.enumerate_formats()
        return _("None") if not formats else ", ".join(formats)

    @classmethod
    def clear(cls) -> None:
        cls._handlers.clear()
        cls._priorities.clear()
        cls._discovered = False

    @classmethod
    def disable_autodiscovery(cls) -> None:
        cls.clear()
        cls._discovered = True

    @classmethod
    def discover(cls) -> None:
        package_path = Path(__file__).parent / "Formats"
        for _, module_name, _ in pkgutil.iter_modules([str(package_path)]):
            module = importlib.import_module(f"PySubtitle.Formats.{module_name}")
            for _, obj in inspect.getmembers(module, inspect.isclass):
                if issubclass(obj, SubtitleFileHandler) and obj is not SubtitleFileHandler:
                    cls.register_handler(obj)
        cls._discovered = True

    @classmethod
    def _ensure_discovered(cls) -> None:
        if not cls._discovered:
            cls.discover()
