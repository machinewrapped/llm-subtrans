import srt # type: ignore
from typing import Iterator, TextIO

from PySubtitle.SubtitleFileHandler import SubtitleFileHandler
from PySubtitle.SubtitleLine import SubtitleLine
from PySubtitle.SubtitleError import SubtitleParseError
from PySubtitle.Helpers.Localization import _

class SrtFileHandler(SubtitleFileHandler):
    """
    File handler for SRT subtitle format.
    Encapsulates all SRT library usage for file I/O operations.
    """
    
    def parse_file(self, file_obj: TextIO) -> Iterator[SubtitleLine]:
        """
        Parse SRT file content and yield SubtitleLine objects.
        """
        yield from self._parse_srt_items(file_obj)
    
    def parse_string(self, content: str) -> Iterator[SubtitleLine]:
        """
        Parse SRT string content and yield SubtitleLine objects.
        """
        yield from self._parse_srt_items(content)

    def compose_lines(self, lines: list[SubtitleLine], reindex: bool = True) -> str:
        """
        Compose subtitle lines into SRT format string.
        
        Args:
            lines: List of SubtitleLine objects to compose
            reindex: Whether to renumber lines sequentially
            
        Returns:
            str: SRT formatted subtitle content
        """
        # Convert SubtitleLine objects to srt.Subtitle objects for composition
        srt_items = []
        for i, line in enumerate(lines):
            if line.text and line.start is not None and line.end is not None:
                # Create srt.Subtitle object
                index = i + 1 if reindex else line.number
                srt_item = srt.Subtitle(
                    index=index,
                    start=line.start,
                    end=line.end,
                    content=line.text,
                    proprietary=""
                )
                srt_items.append(srt_item)
        
        return srt.compose(srt_items, reindex=False)  # We handle reindexing above
    
    def get_file_extensions(self) -> list[str]:
        """
        Get file extensions supported by this handler.
        
        Returns:
            list[str]: List of file extensions
        """
        return ['.srt']

    def _parse_srt_items(self, source) -> Iterator[SubtitleLine]:
        """
        Internal helper to parse SRT items from a file object or string and yield SubtitleLine objects.
        Handles error translation to SubtitleParseError.
        """
        try:
            srt_items = list(srt.parse(source))
            for srt_item in srt_items:
                line = SubtitleLine.Construct(
                    number=srt_item.index,
                    start=srt_item.start,
                    end=srt_item.end,
                    text=srt_item.content,
                    metadata={
                        "proprietary": getattr(srt_item, 'proprietary', '')
                    }
                )
                yield line
                
        except srt.SRTParseError as e:
            raise SubtitleParseError(_("Failed to parse SRT: {}" ).format(str(e)), e)
        except Exception as e:
            raise SubtitleParseError(_("Unexpected error parsing SRT: {}" ).format(str(e)), e)
    
