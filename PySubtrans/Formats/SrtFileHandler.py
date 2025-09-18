import logging
import srt # type: ignore
from collections.abc import Iterator
from typing import TextIO

from PySubtrans.SubtitleFileHandler import (
    SubtitleFileHandler,
    default_encoding,
    fallback_encoding,
)
from PySubtrans.SubtitleLine import SubtitleLine
from PySubtrans.SubtitleData import SubtitleData
from PySubtrans.SubtitleError import SubtitleParseError
from PySubtrans.Helpers.Localization import _

class SrtFileHandler(SubtitleFileHandler):
    """
    File handler for SRT subtitle format.
    Encapsulates all SRT library usage for file I/O operations.
    SRT is a simple format with minimal metadata.
    """
    
    SUPPORTED_EXTENSIONS = {'.srt': 10}

    def load_file(self, path: str) -> SubtitleData:
        try:
            with open(path, 'r', encoding=default_encoding, newline='') as f:
                return self.parse_file(f)
        except UnicodeDecodeError:
            with open(path, 'r', encoding=fallback_encoding, newline='') as f:
                return self.parse_file(f)
    
    def parse_file(self, file_obj: TextIO) -> SubtitleData:
        """
        Parse SRT file content and return SubtitleData with lines and metadata.
        """
        lines = list(self._parse_srt_items(file_obj))
        return SubtitleData(lines=lines, metadata={}, detected_format='.srt')
    
    def parse_string(self, content: str) -> SubtitleData:
        """
        Parse SRT string content and return SubtitleData with lines and metadata.
        """
        lines = list(self._parse_srt_items(content))
        return SubtitleData(lines=lines, metadata={}, detected_format='.srt')

    def compose(self, data: SubtitleData) -> str:
        """
        Compose subtitle lines into SRT format string.
        
        Args:
            data: SubtitleData containing lines and file metadata
            
        Returns:
            str: SRT formatted subtitle content
        """
        from PySubtrans.Helpers.Text import IsRightToLeftText
        
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

        # Log a warning if any lines had no text or start time
        if len(output_lines) < len(data.lines):
            num_invalid = len([line for line in data.lines if line.start is None])
            if num_invalid:
                logging.warning(_("{} lines were invalid and were not written to the output file").format(num_invalid))

            num_empty = len([line for line in data.lines if not line.text])
            if num_empty:
                logging.warning(_("{} lines were empty and were not written to the output file").format(num_empty))

        # Add RTL markers if required
        if data.metadata.get('add_rtl_markers'):
            for line in output_lines:
                if line.text and IsRightToLeftText(line.text) and not line.text.startswith("\u202b"):
                    line.text = f"\u202b{line.text}\u202c"
        

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
        
        return srt.compose(srt_items, reindex=False)

    def _parse_srt_items(self, source) -> Iterator[SubtitleLine]:
        """
        Internal helper to parse SRT items from a file object or string and yield SubtitleLine objects.
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
                
        except UnicodeDecodeError:
            raise  # Re-raise UnicodeDecodeError for fallback handling
        except srt.SRTParseError as e:
            raise SubtitleParseError(_("Failed to parse SRT: {}" ).format(str(e)), e)
        except Exception as e:
            raise SubtitleParseError(_("Unexpected error parsing SRT: {}" ).format(str(e)), e)
    
