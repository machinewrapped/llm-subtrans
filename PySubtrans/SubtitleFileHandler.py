from abc import ABC, abstractmethod
from typing import TextIO
import os

from PySubtrans.SubtitleData import SubtitleData

# Default encodings for reading subtitle files
default_encoding = os.getenv('DEFAULT_ENCODING', 'utf-8')
fallback_encoding = os.getenv('FALLBACK_ENCODING', 'iso-8859-1')


class SubtitleFileHandler(ABC):
    """
    Abstract interface for reading and writing subtitle files.

    Implementations handle format-specific operations while business logic remains format-agnostic.
    """

    SUPPORTED_EXTENSIONS: dict[str, int] = {}

    @abstractmethod
    def parse_file(self, file_obj: TextIO) -> SubtitleData:
        """
        Parse subtitle file content and return lines with file-level metadata.

        Returns:
            SubtitleData: Parsed subtitle lines and metadata

        Raises:
            SubtitleParseError: If parsing fails
        
        """
        raise NotImplementedError

    @abstractmethod
    def parse_string(self, content: str) -> SubtitleData:
        """
        Parse subtitle string content and return lines with file-level metadata.

        Returns:
            SubtitleData: Parsed subtitle lines and metadata

        Raises:
            SubtitleParseError: If parsing fails
        """
        raise NotImplementedError

    @abstractmethod
    def compose(self, data: SubtitleData) -> str:
        """
        Compose subtitle lines into text for saving or exporting.

        Args:
            data: SubtitleData containing subtitle content and metadata

        Returns:
            str: Subtitle content and metadata content in the file handler's format
        """
        raise NotImplementedError

    @abstractmethod
    def load_file(self, path: str) -> SubtitleData:
        """
        Open a subtitle file and parse it.

        Returns:
            SubtitleData: Parsed subtitle lines and metadata

        Raises:
            SubtitleParseError: If parsing fails
            UnicodeDecodeError: If file is in an unsupported encoding            
        """
        raise NotImplementedError

    def get_file_extensions(self) -> list[str]:
        """
        Get file extensions supported by this handler.
        """
        return list(self.__class__.SUPPORTED_EXTENSIONS.keys())

    def get_extension_priorities(self) -> dict[str, int]:
        """
        Get priority for each supported extension.

        Returns:
            dict: Mapping of file extensions to their priority (higher = more preferred)
        """
        return self.__class__.SUPPORTED_EXTENSIONS.copy()
