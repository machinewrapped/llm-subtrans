from abc import ABC, abstractmethod
from typing import Iterator, TextIO
from PySubtitle.SubtitleLine import SubtitleLine

class SubtitleFileHandler(ABC):
    """
    Abstract interface for reading and writing subtitle files.
    Implementations handle format-specific operations while business logic
    remains format-agnostic.
    """
    
    @abstractmethod
    def parse_file(self, file_obj: TextIO) -> Iterator[SubtitleLine]:
        """
        Parse subtitle file content and yield SubtitleLine objects.
        
        Args:
            file_obj: Open file object to read from
            
        Yields:
            SubtitleLine: Parsed subtitle lines
            
        Raises:
            SubtitleParseError: If file cannot be parsed
        """
        pass
    
    @abstractmethod
    def parse_string(self, content: str) -> Iterator[SubtitleLine]:
        """
        Parse subtitle string content and yield SubtitleLine objects.
        
        Args:
            content: String content to parse
            
        Yields:
            SubtitleLine: Parsed subtitle lines
            
        Raises:
            SubtitleParseError: If content cannot be parsed
        """
        pass
    
    @abstractmethod
    def compose_lines(self, lines: list[SubtitleLine], reindex: bool = True) -> str:
        """
        Compose subtitle lines into file format string.
        
        Args:
            lines: List of SubtitleLine objects to compose
            reindex: Whether to renumber lines sequentially
            
        Returns:
            str: Formatted subtitle content
        """
        pass
    
    @abstractmethod
    def get_file_extensions(self) -> list[str]:
        """
        Get file extensions supported by this handler.
        
        Returns:
            list[str]: List of file extensions (e.g., ['.srt'])
        """
        pass