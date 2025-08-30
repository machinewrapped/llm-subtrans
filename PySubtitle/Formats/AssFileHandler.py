import pysubs2
import pysubs2.time
from datetime import timedelta
from typing import TextIO

from PySubtitle.Helpers.SimpleColor import SimpleColor
from PySubtitle.SubtitleFileHandler import SubtitleFileHandler
from PySubtitle.SubtitleLine import SubtitleLine
from PySubtitle.SubtitleData import SubtitleData
from PySubtitle.SubtitleError import SubtitleParseError
from PySubtitle.Helpers.Localization import _


class AssFileHandler(SubtitleFileHandler):
    """
    File handler for Advanced SubStation Alpha (ASS/SSA) subtitle format using pysubs2 library.
    Provides professional-grade ASS handling with full metadata preservation.
    """
    
    SUPPORTED_EXTENSIONS = {'.ass': 10, '.ssa': 10}
    
    def parse_file(self, file_obj: TextIO) -> SubtitleData:
        """
        Parse ASS file content and return SubtitleData with lines and metadata.
        """
        try:
            # pysubs2 expects file path or string content, so read the file
            content = file_obj.read()
            subs = pysubs2.SSAFile.from_string(content)
            
            lines = []
            for index, line in enumerate(subs, 1):
                lines.append(self._pysubs2_to_subtitle_line(line, index))
            
            # Extract serializable metadata using helper
            metadata = self._parse_metadata(subs)
            
            return SubtitleData(lines=lines, metadata=metadata)
                
        except Exception as e:
            raise SubtitleParseError(_("Failed to parse ASS file: {}").format(str(e)), e)
    
    def parse_string(self, content: str) -> SubtitleData:
        """
        Parse ASS string content and return SubtitleData with lines and metadata.
        """
        try:
            # pysubs2 can load from string
            subs = pysubs2.SSAFile.from_string(content)
            
            lines = []
            for index, line in enumerate(subs, 1):
                lines.append(self._pysubs2_to_subtitle_line(line, index))
            
            # Extract serializable metadata using helper
            metadata = self._parse_metadata(subs)
            
            return SubtitleData(lines=lines, metadata=metadata)
                
        except Exception as e:
            raise SubtitleParseError(_("Failed to parse ASS content: {}").format(str(e)), e)
    
    def compose(self, data: SubtitleData) -> str:
        """
        Compose subtitle lines into ASS format string using metadata.
        
        Args:
            data: SubtitleData containing lines and file metadata
            
        Returns:
            str: ASS formatted subtitle content
        """
        # Create pysubs2 SSAFile
        subs = pysubs2.SSAFile()
        
        # Restore metadata using helper
        if data.metadata:
            self._build_metadata(subs, data.metadata)
        
        # Convert SubtitleLines to pysubs2 format
        for line in data.lines:
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
        if line.start:
            event.start = pysubs2.time.make_time(s=line.start.total_seconds())
        else:
            event.start = 0
            
        if line.end:
            event.end = pysubs2.time.make_time(s=line.end.total_seconds())
        else:
            event.end = 0
        
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

    def _parse_metadata(self, subs : pysubs2.SSAFile) -> dict:
        """
        Convert pysubs2 metadata to JSON-serializable format.
        Handles Color objects and other pysubs2-specific types.
        """
        # Extract serializable metadata from the pysubs2 file
        metadata = {
            'format': 'ass',
            'info': dict(subs.info),  # Script info section
            'aegisub_project': dict(subs.aegisub_project) if hasattr(subs, 'aegisub_project') else {}
        }
        
        # Convert styles, handling Color objects
        styles = {}
        for name, style in subs.styles.items():
            style_dict = style.as_dict()
            
            # Convert pysubs2.Color objects to SimpleColor dicts
            color_fields = ['primarycolor', 'secondarycolor', 'tertiarycolor', 'outlinecolor', 'backcolor']
            for field in color_fields:
                if field in style_dict and isinstance(style_dict[field], pysubs2.Color):
                    style_dict[field] = SimpleColor.from_pysubs2(style_dict[field]).to_dict()
            
            styles[name] = style_dict
        
        metadata['styles'] = styles
        return metadata
    
    def _build_metadata(self, subs : pysubs2.SSAFile, metadata : dict) -> None:
        """
        Restore pysubs2 metadata from JSON-serialized format.
        Converts SimpleColor dicts back to pysubs2.Color objects.
        """
        # Restore script info from metadata
        if 'info' in metadata:
            subs.info.update(metadata['info'])
        
        # Restore styles from metadata
        if 'styles' in metadata:
            # Clear default styles that pysubs2 creates automatically to avoid conflicts
            subs.styles.clear()
            
            for style_name, style_fields in metadata['styles'].items():
                # Convert SimpleColor dicts back to pysubs2.Color objects
                style_data = style_fields.copy()
                color_fields = ['primarycolor', 'secondarycolor', 'tertiarycolor', 'outlinecolor', 'backcolor']
                
                for field in color_fields:
                    if field in style_data and isinstance(style_data[field], dict):
                        # Check if it's a SimpleColor dict representation
                        if all(key in style_data[field] for key in ['r', 'g', 'b']):
                            style_data[field] = SimpleColor.from_dict(style_data[field]).to_pysubs2()
                
                style = pysubs2.SSAStyle(**style_data)
                subs.styles[style_name] = style
        
        # Restore aegisub project data if present
        if 'aegisub_project' in metadata and hasattr(subs, 'aegisub_project'):
            subs.aegisub_project.update(metadata['aegisub_project'])
    
