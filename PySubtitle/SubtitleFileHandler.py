from abc import ABC, abstractmethod
from typing import TextIO
import os

from PySubtitle.SubtitleData import SubtitleData

# Default encodings for reading subtitle files
default_encoding = os.getenv('DEFAULT_ENCODING', 'utf-8')
fallback_encoding = os.getenv('FALLBACK_ENCODING', 'iso-8859-1')


class SubtitleFileHandler(ABC):
    """Abstract interface for reading and writing subtitle files."""

    SUPPORTED_EXTENSIONS: dict[str, int] = {}

    @abstractmethod
    def parse_file(self, file_obj: TextIO) -> SubtitleData:
        """Parse subtitle file content and return lines with file-level metadata."""
        raise NotImplementedError

    @abstractmethod
    def parse_string(self, content: str) -> SubtitleData:
        """Parse subtitle string content and return lines with file-level metadata."""
        raise NotImplementedError

    @abstractmethod
    def compose(self, data: SubtitleData) -> str:
        """Compose subtitle lines into file format string using file-level metadata."""
        raise NotImplementedError

    @abstractmethod
    def load_file(self, path: str) -> SubtitleData:
        """Open a subtitle file and parse it, handling encoding fallbacks as needed."""
        raise NotImplementedError

    def get_file_extensions(self) -> list[str]:
        """Get file extensions supported by this handler."""
        return list(self.__class__.SUPPORTED_EXTENSIONS.keys())

    def get_extension_priorities(self) -> dict[str, int]:
        """Get priority for each supported extension."""
        return self.__class__.SUPPORTED_EXTENSIONS.copy()
