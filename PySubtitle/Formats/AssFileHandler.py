import re
from datetime import timedelta
from typing import Iterator, TextIO

from PySubtitle.SubtitleFileHandler import SubtitleFileHandler
from PySubtitle.SubtitleLine import SubtitleLine
from PySubtitle.SubtitleError import SubtitleParseError
from PySubtitle.Helpers.Localization import _

class AssFileHandler(SubtitleFileHandler):
    """
    File handler for Advanced SubStation Alpha (ASS/SSA) subtitle format.
    Handles parsing and composition of ASS files including styles and dialogue events.
    """
    
    def __init__(self):
        """Initialize ASS file handler with default formatting templates."""
        self.script_info = {}
        self.styles = {}
        self.events_format = "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
        
    def parse_file(self, file_obj: TextIO) -> Iterator[SubtitleLine]:
        """
        Parse ASS file content and yield SubtitleLine objects.
        """
        content = file_obj.read()
        yield from self.parse_string(content)
    
    def parse_string(self, content: str) -> Iterator[SubtitleLine]:
        """
        Parse ASS string content and yield SubtitleLine objects.
        """
        try:
            # Split content into sections
            sections = self._parse_sections(content)
            
            # Parse script info and styles for metadata
            if '[Script Info]' in sections:
                self.script_info = self._parse_script_info(sections['[Script Info]'])
            
            if '[V4+ Styles]' in sections:
                self.styles = self._parse_styles(sections['[V4+ Styles]'])
            elif '[V4 Styles]' in sections:
                self.styles = self._parse_styles(sections['[V4 Styles]'])
                
            # Parse dialogue events
            if '[Events]' in sections:
                yield from self._parse_events(sections['[Events]'])
            else:
                raise SubtitleParseError(_("No events section found in ASS file"))
                
        except Exception as e:
            if isinstance(e, SubtitleParseError):
                raise
            raise SubtitleParseError(_("Failed to parse ASS file: {}").format(str(e)), e)
    
    def compose_lines(self, lines: list[SubtitleLine], reindex: bool = True) -> str:
        """
        Compose subtitle lines into ASS format string.
        
        Args:
            lines: List of SubtitleLine objects to compose
            reindex: Whether to renumber lines sequentially
            
        Returns:
            str: ASS formatted subtitle content
        """
        output = []
        
        # Write script info section
        output.append("[Script Info]")
        script_info = getattr(self, 'script_info', {}) or {
            'Title': 'Translated Subtitles',
            'ScriptType': 'v4.00+',
            'PlayDepth': '0',
            'ScaledBorderAndShadow': 'Yes',
            'WrapStyle': '0'
        }
        for key, value in script_info.items():
            output.append(f"{key}: {value}")
        output.append("")
        
        # Write styles section
        output.append("[V4+ Styles]")
        output.append("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding")
        
        # Use existing styles or create a default one
        styles = getattr(self, 'styles', {})
        if not styles:
            styles['Default'] = {
                'Fontname': 'Arial',
                'Fontsize': '50',
                'PrimaryColour': '&H00FFFFFF',
                'SecondaryColour': '&H0000FFFF',
                'OutlineColour': '&H00000000',
                'BackColour': '&H00000000',
                'Bold': '0',
                'Italic': '0',
                'Underline': '0',
                'StrikeOut': '0',
                'ScaleX': '100',
                'ScaleY': '100',
                'Spacing': '0',
                'Angle': '0',
                'BorderStyle': '1',
                'Outline': '2',
                'Shadow': '0',
                'Alignment': '2',
                'MarginL': '30',
                'MarginR': '30',
                'MarginV': '30',
                'Encoding': '1'
            }
        
        for style_name, style_data in styles.items():
            style_line = f"Style: {style_name}"
            for field in ['Fontname', 'Fontsize', 'PrimaryColour', 'SecondaryColour', 
                         'OutlineColour', 'BackColour', 'Bold', 'Italic', 'Underline', 
                         'StrikeOut', 'ScaleX', 'ScaleY', 'Spacing', 'Angle', 
                         'BorderStyle', 'Outline', 'Shadow', 'Alignment', 
                         'MarginL', 'MarginR', 'MarginV', 'Encoding']:
                style_line += f",{style_data.get(field, '0')}"
            output.append(style_line)
        output.append("")
        
        # Write events section
        output.append("[Events]")
        output.append(self.events_format)
        
        for i, line in enumerate(lines):
            if line.text and line.start is not None and line.end is not None:
                index = i + 1 if reindex else line.number
                
                # Extract ASS-specific metadata or use defaults
                metadata = line.metadata or {}
                layer = metadata.get('layer', 0)
                style = metadata.get('style', 'Default')
                name = metadata.get('name', '')
                margin_l = metadata.get('margin_l', 0)
                margin_r = metadata.get('margin_r', 0)
                margin_v = metadata.get('margin_v', 0)
                effect = metadata.get('effect', '')
                
                # Format time as ASS format (H:MM:SS.CC)
                start_time = self._timedelta_to_ass_time(line.start)
                end_time = self._timedelta_to_ass_time(line.end)
                
                # Clean and format text
                text = line.text.replace('\n', '\\N')
                
                dialogue_line = f"Dialogue: {layer},{start_time},{end_time},{style},{name},{margin_l},{margin_r},{margin_v},{effect},{text}"
                output.append(dialogue_line)
        
        return '\n'.join(output)
    
    def get_file_extensions(self) -> list[str]:
        """
        Get file extensions supported by this handler.
        
        Returns:
            list[str]: List of file extensions
        """
        return ['.ass', '.ssa']
    
    def _parse_sections(self, content: str) -> dict[str, str]:
        """Parse ASS file content into sections."""
        sections = {}
        current_section = None
        section_lines = []
        
        for line in content.split('\n'):
            line = line.strip()
            
            # Skip empty lines and comments at file level
            if not line or line.startswith(';'):
                continue
                
            # Check for section header
            if line.startswith('[') and line.endswith(']'):
                # Save previous section
                if current_section and section_lines:
                    sections[current_section] = '\n'.join(section_lines)
                
                # Start new section
                current_section = line
                section_lines = []
            elif current_section:
                section_lines.append(line)
        
        # Save last section
        if current_section and section_lines:
            sections[current_section] = '\n'.join(section_lines)
            
        return sections
    
    def _parse_script_info(self, section_content: str) -> dict[str, str]:
        """Parse script info section."""
        script_info = {}
        
        for line in section_content.split('\n'):
            line = line.strip()
            if not line or line.startswith(';'):
                continue
                
            if ':' in line:
                key, value = line.split(':', 1)
                script_info[key.strip()] = value.strip()
                
        return script_info
    
    def _parse_styles(self, section_content: str) -> dict[str, dict[str, str]]:
        """Parse styles section."""
        styles = {}
        format_fields = []
        
        for line in section_content.split('\n'):
            line = line.strip()
            if not line or line.startswith(';'):
                continue
                
            if line.startswith('Format:'):
                # Parse format line to get field order
                format_part = line[7:].strip()  # Remove 'Format:'
                format_fields = [field.strip() for field in format_part.split(',')]
            elif line.startswith('Style:'):
                # Parse style line
                style_part = line[6:].strip()  # Remove 'Style:'
                style_values = [value.strip() for value in style_part.split(',')]
                
                if format_fields and len(style_values) >= len(format_fields):
                    style_name = style_values[0]
                    style_data = {}
                    
                    # Map values to format fields (skip Name field)
                    for i, field in enumerate(format_fields[1:], 1):
                        if i < len(style_values):
                            style_data[field] = style_values[i]
                    
                    styles[style_name] = style_data
                    
        return styles
    
    def _parse_events(self, section_content: str) -> Iterator[SubtitleLine]:
        """Parse events section and yield SubtitleLine objects."""
        format_fields = []
        event_index = 1
        
        for line in section_content.split('\n'):
            line = line.strip()
            if not line or line.startswith(';'):
                continue
                
            if line.startswith('Format:'):
                # Parse format line to get field order
                format_part = line[7:].strip()  # Remove 'Format:'
                format_fields = [field.strip() for field in format_part.split(',')]
            elif line.startswith('Dialogue:'):
                # Parse dialogue line
                dialogue_part = line[9:].strip()  # Remove 'Dialogue:'
                dialogue_values = [value.strip() for value in dialogue_part.split(',', len(format_fields) - 1)]
                
                if format_fields and len(dialogue_values) >= len(format_fields):
                    # Create mapping of field names to values
                    event_data = {}
                    for i, field in enumerate(format_fields):
                        if i < len(dialogue_values):
                            event_data[field] = dialogue_values[i]
                    
                    # Extract required fields
                    start_time = self._ass_time_to_timedelta(event_data.get('Start', '0:00:00.00'))
                    end_time = self._ass_time_to_timedelta(event_data.get('End', '0:00:00.00'))
                    text = event_data.get('Text', '').replace('\\N', '\n').replace('\\n', '\n')
                    
                    # Create metadata for ASS-specific fields
                    metadata = {
                        'format': 'ass',
                        'layer': int(event_data.get('Layer', 0)),
                        'style': event_data.get('Style', 'Default'),
                        'name': event_data.get('Name', ''),
                        'margin_l': int(event_data.get('MarginL', 0)),
                        'margin_r': int(event_data.get('MarginR', 0)),
                        'margin_v': int(event_data.get('MarginV', 0)),
                        'effect': event_data.get('Effect', '')
                    }
                    
                    # Create SubtitleLine
                    subtitle_line = SubtitleLine.Construct(
                        number=event_index,
                        start=start_time,
                        end=end_time,
                        text=text,
                        metadata=metadata
                    )
                    
                    yield subtitle_line
                    event_index += 1
    
    def _ass_time_to_timedelta(self, ass_time: str) -> timedelta:
        """Convert ASS time format (H:MM:SS.CC) to timedelta."""
        try:
            # ASS time format: H:MM:SS.CC where CC is centiseconds
            time_match = re.match(r'(\d+):(\d{2}):(\d{2})\.(\d{2})', ass_time)
            if not time_match:
                return timedelta(seconds=0)
            
            hours = int(time_match.group(1))
            minutes = int(time_match.group(2))
            seconds = int(time_match.group(3))
            centiseconds = int(time_match.group(4))
            
            return timedelta(
                hours=hours,
                minutes=minutes,
                seconds=seconds,
                milliseconds=centiseconds * 10  # Convert centiseconds to milliseconds
            )
        except (ValueError, AttributeError):
            return timedelta(seconds=0)
    
    def _timedelta_to_ass_time(self, td: timedelta) -> str:
        """Convert timedelta to ASS time format (H:MM:SS.CC)."""
        total_seconds = int(td.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        centiseconds = int((td.microseconds / 1000) / 10)  # Convert microseconds to centiseconds
        
        return f"{hours}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"