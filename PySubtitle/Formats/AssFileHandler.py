import pysubs2
from datetime import timedelta
from typing import Iterator, TextIO

from PySubtitle.SubtitleFileHandler import SubtitleFileHandler
from PySubtitle.SubtitleLine import SubtitleLine
from PySubtitle.SubtitleError import SubtitleParseError
from PySubtitle.Helpers.Localization import _

class AssFileHandler(SubtitleFileHandler):
    """
    File handler for Advanced SubStation Alpha (ASS/SSA) subtitle format using pysubs2 library.
    Provides professional-grade ASS handling with full metadata preservation.
    """
    
    SUPPORTED_EXTENSIONS = {'.ass': 10, '.ssa': 10}
    
    def parse_file(self, file_obj: TextIO) -> Iterator[SubtitleLine]:
        """
        Parse ASS file content and yield SubtitleLine objects using pysubs2.
        """
        try:
            # pysubs2 expects file path or string content, so read the file
            content = file_obj.read()
            subs = pysubs2.SSAFile.from_string(content)
            
            for index, line in enumerate(subs, 1):
                yield self._pysubs2_to_subtitle_line(line, index)
                
        except Exception as e:
            raise SubtitleParseError(_("Failed to parse ASS file: {}").format(str(e)), e)
    
    def parse_string(self, content: str) -> Iterator[SubtitleLine]:
        """
        Parse ASS string content and yield SubtitleLine objects using pysubs2.
        """
        try:
            # pysubs2 can load from string
            subs = pysubs2.SSAFile.from_string(content)
            
            for index, line in enumerate(subs, 1):
                yield self._pysubs2_to_subtitle_line(line, index)
                
        except Exception as e:
            raise SubtitleParseError(_("Failed to parse ASS content: {}").format(str(e)), e)
    
    def compose_lines(self, lines: list[SubtitleLine], reindex: bool = True) -> str:
        """
        Compose subtitle lines into ASS format string using pysubs2.
        
        Args:
            lines: List of SubtitleLine objects to compose
            reindex: Whether to renumber lines sequentially (ignored for ASS)
            
        Returns:
            str: ASS formatted subtitle content
        """
        # Create pysubs2 SSAFile
        subs = pysubs2.SSAFile()
        
        # Convert SubtitleLines to pysubs2 format
        for line in lines:
            if line.text and line.start is not None and line.end is not None:
                pysubs2_line = self._subtitle_line_to_pysubs2(line)
                subs.append(pysubs2_line)
        
        # Return as string
        return subs.to_string("ass")
    
    
    def _pysubs2_to_subtitle_line(self, pysubs2_line: pysubs2.SSAEvent, index: int) -> SubtitleLine:
        """Convert pysubs2 SSAEvent to SubtitleLine with metadata preservation."""
        
        # Convert timing from milliseconds to timedelta
        start = timedelta(milliseconds=pysubs2_line.start)
        end = timedelta(milliseconds=pysubs2_line.end)
        
        # Extract text content using plaintext for GUI compatibility (converts \\N to \n)
        text = pysubs2_line.plaintext
        
        # Create comprehensive metadata from pysubs2 properties
        # This is "pass-through" - we preserve everything for format fidelity
        metadata = {
            'format': 'ass',
            'style': pysubs2_line.style,
            'layer': pysubs2_line.layer,
            'name': pysubs2_line.name,
            'margin_l': pysubs2_line.marginl,
            'margin_r': pysubs2_line.marginr,
            'margin_v': pysubs2_line.marginv,
            'effect': pysubs2_line.effect,
            'type': pysubs2_line.type,
            # Store original pysubs2 properties for perfect round-trip
            '_pysubs2_original': {
                'style': pysubs2_line.style,
                'layer': pysubs2_line.layer,
                'name': pysubs2_line.name,
                'marginl': pysubs2_line.marginl,
                'marginr': pysubs2_line.marginr,
                'marginv': pysubs2_line.marginv,
                'effect': pysubs2_line.effect,
                'type': pysubs2_line.type
            }
        }
        
        return SubtitleLine.Construct(
            number=index,
            start=start,
            end=end,
            text=text,
            metadata=metadata
        )
    
    def _subtitle_line_to_pysubs2(self, line: SubtitleLine) -> pysubs2.SSAEvent:
        """Convert SubtitleLine back to pysubs2 SSAEvent using preserved metadata."""
        
        # Create pysubs2 event
        event = pysubs2.SSAEvent()
        
        # Set timing (convert from timedelta to milliseconds)
        event.start = int(line.start.total_seconds() * 1000) if line.start else 0
        event.end = int(line.end.total_seconds() * 1000) if line.end else 0
        
        # Set text using plaintext property (automatically converts \n to \\N)
        event.plaintext = line.text or ""
        
        # Restore metadata if available, otherwise use sensible defaults
        metadata = line.metadata or {}
        
        # Check for preserved pysubs2 original data first (perfect round-trip)
        if '_pysubs2_original' in metadata:
            original = metadata['_pysubs2_original']
            event.style = original.get('style', 'Default')
            event.layer = original.get('layer', 0)
            event.name = original.get('name', '')
            event.marginl = original.get('marginl', 0)
            event.marginr = original.get('marginr', 0)
            event.marginv = original.get('marginv', 0)
            event.effect = original.get('effect', '')
            event.type = original.get('type', 'Dialogue')
        else:
            # Fall back to our standard metadata fields
            event.style = metadata.get('style', 'Default')
            event.layer = metadata.get('layer', 0)
            event.name = metadata.get('name', '')
            event.marginl = metadata.get('margin_l', 0)
            event.marginr = metadata.get('margin_r', 0)
            event.marginv = metadata.get('margin_v', 0)
            event.effect = metadata.get('effect', '')
            event.type = 'Dialogue'  # Default for most subtitle lines
        
        return event