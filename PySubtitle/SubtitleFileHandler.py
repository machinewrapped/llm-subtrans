from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any, TextIO

from PySubtitle.SubtitleLine import SubtitleLine
from PySubtitle.SubtitleData import SubtitleData

class SubtitleFileHandler(ABC):
    """
    Abstract interface for reading and writing subtitle files.
    Implementations handle format-specific operations while business logic
    remains format-agnostic.
    """
    
    SUPPORTED_EXTENSIONS : dict[str, int] = {}
    
    @abstractmethod
    def parse_file(self, file_obj: TextIO) -> SubtitleData:
        """
        Parse subtitle file content and return lines with file-level metadata.
        
        Args:
            file_obj: Open file object to read from
            
        Returns:
            SubtitleData: Container with parsed lines and file metadata
            
        Raises:
            SubtitleParseError: If file cannot be parsed
        """
        pass
    
    @abstractmethod
    def parse_string(self, content: str) -> SubtitleData:
        """
        Parse subtitle string content and return lines with file-level metadata.
        
        Args:
            content: String content to parse
            
        Returns:
            SubtitleData: Container with parsed lines and file metadata
            
        Raises:
            SubtitleParseError: If content cannot be parsed
        """
        pass
    
    @abstractmethod
    def compose(self, data: SubtitleData) -> str:
        """
        Compose subtitle lines into file format string using file-level metadata.
        
        Args:
            data: Container with subtitle lines and file metadata
            
        Returns:
            str: Formatted subtitle content
        """
        pass
    
    def get_file_extensions(self) -> list[str]:
        """
        Get file extensions supported by this handler.
        
        Returns:
            list[str]: List of file extensions (e.g., ['.srt'])
        """
        return list(self.__class__.SUPPORTED_EXTENSIONS.keys())
    
    def get_extension_priorities(self) -> dict[str, int]:
        """
        Get priority for each supported extension.
        Higher priority handlers override lower priority ones.
        
        Returns:
            dict[str, int]: Mapping of extensions to priorities
        """
        return self.__class__.SUPPORTED_EXTENSIONS.copy()