import srt # type: ignore
from collections.abc import Iterator
from typing import TextIO

from PySubtitle.SubtitleFileHandler import SubtitleFileHandler
from PySubtitle.SubtitleLine import SubtitleLine
from PySubtitle.SubtitleData import SubtitleData
from PySubtitle.SubtitleError import SubtitleParseError
from PySubtitle.Helpers.Localization import _

class SrtFileHandler(SubtitleFileHandler):
    """
    File handler for SRT subtitle format.
    Encapsulates all SRT library usage for file I/O operations.
    """
    
    SUPPORTED_EXTENSIONS = {'.srt': 10}
    
    def parse_file(self, file_obj: TextIO) -> SubtitleData:
        """
        Parse SRT file content and return SubtitleData with lines and metadata.
        """
        lines = list(self._parse_srt_items(file_obj))
        metadata = {'format': 'srt'}  # SRT has minimal file-level metadata
        return SubtitleData(lines=lines, metadata=metadata)
    
    def parse_string(self, content: str) -> SubtitleData:
        """
        Parse SRT string content and return SubtitleData with lines and metadata.
        """
        lines = list(self._parse_srt_items(content))
        metadata = {'format': 'srt'}  # SRT has minimal file-level metadata
        return SubtitleData(lines=lines, metadata=metadata)

    def compose(self, data: SubtitleData) -> str:
        """
        Compose subtitle lines into SRT format string using metadata.
        
        Args:
            data: SubtitleData containing lines and file metadata
            
        Returns:
            str: SRT formatted subtitle content
        """
        from PySubtitle.Helpers.Text import IsRightToLeftText
        
        # Filter out invalid lines and renumber for SRT compliance
        output_lines = []
        start_number = data.start_line_number or 1
        line_number = start_number
        
        for line in data.lines:
            if line.text and line.start is not None and line.end is not None:
                output_lines.append(SubtitleLine.Construct(
                    line_number, line.start, line.end, line.text, line.metadata
                ))
                line_number += 1
        
        # Handle RTL markers if requested (marginal case)
        if data.metadata.get('add_rtl_markers'):
            for line in output_lines:
                if line.text and IsRightToLeftText(line.text) and not line.text.startswith("\u202b"):
                    line.text = f"\u202b{line.text}\u202c"
        
        # Convert SubtitleLine objects to srt.Subtitle objects for composition
        srt_items = []
        for line in output_lines:
            proprietary = line.metadata.get('proprietary', '')
            
            srt_item = srt.Subtitle(
                index=line.number,
                start=line.start,
                end=line.end,
                content=line.text,
                proprietary=proprietary
            )
            srt_items.append(srt_item)
        
        return srt.compose(srt_items, reindex=False)  # We handle reindexing above
    

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
    
