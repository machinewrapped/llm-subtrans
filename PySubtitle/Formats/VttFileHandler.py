import regex
from datetime import timedelta
from typing import TextIO

from PySubtitle.SubtitleFileHandler import (
    SubtitleFileHandler,
    default_encoding,
    fallback_encoding,
)
from PySubtitle.SubtitleLine import SubtitleLine
from PySubtitle.SubtitleData import SubtitleData
from PySubtitle.SubtitleError import SubtitleParseError
from PySubtitle.Helpers.Localization import _


class VttFileHandler(SubtitleFileHandler):
    """
    Native WebVTT subtitle format handler with metadata pass-through.
    
    Captures VTT-specific features like cue settings, STYLE blocks, and voice tags
    as metadata for round-trip preservation while focusing on translation workflow.
    """
    
    SUPPORTED_EXTENSIONS = {'.vtt': 10}
    
    # Regex patterns for VTT parsing
    _TIMESTAMP_PATTERN = regex.compile(r'(\d{2,}):(\d{2}):(\d{2})\.(\d{3})\s*-->\s*(\d{2,}):(\d{2}):(\d{2})\.(\d{3})(.*)')
    _VOICE_TAG_PATTERN = regex.compile(r'<v(?:\.[\w.]+)?\s+([^>]+)>')
    _CLOSING_VOICE_TAG_PATTERN = regex.compile(r'</v>')
    _STYLE_BLOCK_START = regex.compile(r'^\s*STYLE\s*$')
    _NOTE_BLOCK_START = regex.compile(r'^\s*NOTE\s')

    def load_file(self, path: str) -> SubtitleData:
        try:
            with open(path, 'r', encoding=default_encoding) as f:
                return self.parse_file(f)
        except UnicodeDecodeError:
            with open(path, 'r', encoding=fallback_encoding) as f:
                return self.parse_file(f)
    
    def parse_file(self, file_obj: TextIO) -> SubtitleData:
        """Parse file content and return SubtitleData with lines and metadata."""
        try:
            content = file_obj.read()
            return self.parse_string(content)
        except UnicodeDecodeError:
            raise  # Re-raise UnicodeDecodeError for fallback handling
        except Exception as e:
            raise SubtitleParseError(_("Failed to parse file: {}").format(str(e)), e)

    def parse_string(self, content: str) -> SubtitleData:
        """Parse string content and return SubtitleData with lines and metadata."""
        try:
            lines = content.splitlines()
            
            # Validate WebVTT header (handle BOM)
            if not lines or not lines[0].strip().lstrip('\ufeff').startswith('WEBVTT'):
                raise SubtitleParseError(_("Invalid WebVTT file: missing WEBVTT header"))
            
            subtitle_lines = []
            file_metadata = {
                'vtt_styles': [],
                'header_text': lines[0].strip()
            }
            
            i = 1
            line_number = 1
            
            while i < len(lines):
                line = lines[i].strip()
                
                # Skip empty lines
                if not line:
                    i += 1
                    continue
                
                # Handle STYLE blocks
                if self._STYLE_BLOCK_START.match(line):
                    style_block, i = self._parse_style_block(lines, i + 1)
                    if style_block:
                        file_metadata['vtt_styles'].append(style_block)
                    continue
                
                # Handle NOTE blocks (skip them)
                if self._NOTE_BLOCK_START.match(line):
                    i = self._skip_note_block(lines, i + 1)
                    continue
                
                # Try to parse as cue identifier + timestamp, or just timestamp
                cue_id = None
                timestamp_line_idx = i
                
                # Check if this line is a cue identifier (next line should be timestamp)
                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if self._TIMESTAMP_PATTERN.match(next_line):
                        cue_id = line
                        timestamp_line_idx = i + 1
                
                # Parse timestamp line
                if timestamp_line_idx < len(lines):
                    timestamp_match = self._TIMESTAMP_PATTERN.match(lines[timestamp_line_idx].strip())
                    if timestamp_match:
                        # Parse timing and cue settings
                        start_time = self._parse_timestamp(timestamp_match.groups()[:4])
                        end_time = self._parse_timestamp(timestamp_match.groups()[4:8])
                        cue_settings = timestamp_match.group(9).strip() if timestamp_match.group(9) else ""
                        
                        # Parse cue text (may be multi-line)
                        cue_text_lines = []
                        i = timestamp_line_idx + 1
                        
                        while i < len(lines) and lines[i].strip():
                            cue_text_lines.append(lines[i])
                            i += 1
                        
                        cue_text = '\n'.join(cue_text_lines) if cue_text_lines else ""
                        
                        # Extract speaker and process text
                        speaker_name = self._extract_speaker_name(cue_text)
                        processed_text = self._process_vtt_text(cue_text)
                        
                        # Build line metadata
                        line_metadata = {}
                        if cue_id:
                            line_metadata['cue_id'] = cue_id
                        if cue_settings:
                            line_metadata['vtt_settings'] = cue_settings
                        if speaker_name:
                            line_metadata['speaker'] = speaker_name
                        
                        subtitle_lines.append(SubtitleLine.Construct(
                            number=line_number,
                            start=start_time,
                            end=end_time,
                            text=processed_text,
                            metadata=line_metadata
                        ))
                        
                        line_number += 1
                        continue
                
                # If we get here, skip this line as unrecognized content
                i += 1
            
            return SubtitleData(
                lines=subtitle_lines, 
                metadata=file_metadata, 
                detected_format='.vtt'
            )
                
        except Exception as e:
            if isinstance(e, SubtitleParseError):
                raise
            raise SubtitleParseError(_("Failed to parse content: {}").format(str(e)), e)
    
    def compose(self, data: SubtitleData) -> str:
        """Compose subtitle lines into WebVTT format string."""
        output_lines = []
        
        # Add header
        header_text = data.metadata.get('header_text', 'WEBVTT')
        output_lines.append(header_text)
        output_lines.append('')  # Blank line after header
        
        # Add STYLE blocks if present
        vtt_styles = data.metadata.get('vtt_styles', [])
        for style_block in vtt_styles:
            output_lines.append('STYLE')
            output_lines.append(style_block)
            output_lines.append('')
        
        # Add cues
        for line in data.lines:
            if line.text and line.start is not None and line.end is not None:
                # Add cue identifier if present
                if line.metadata and 'cue_id' in line.metadata:
                    output_lines.append(line.metadata['cue_id'])
                
                # Format timestamp line with cue settings
                start_time = self._format_timestamp(line.start)
                end_time = self._format_timestamp(line.end)
                timestamp_line = f"{start_time} --> {end_time}"
                
                if line.metadata and 'vtt_settings' in line.metadata:
                    timestamp_line += f" {line.metadata['vtt_settings']}"
                
                output_lines.append(timestamp_line)
                
                # Restore speaker and process text for output
                output_text = self._restore_vtt_text(line.text or "", line.metadata or {})
                output_lines.append(output_text)
                output_lines.append('')  # Blank line after cue
        
        return '\n'.join(output_lines)
    
    def _parse_timestamp(self, time_parts) -> timedelta:
        """Parse timestamp components into timedelta."""
        hours, minutes, seconds, milliseconds = map(int, time_parts)
        return timedelta(hours=hours, minutes=minutes, seconds=seconds, milliseconds=milliseconds)
    
    def _format_timestamp(self, td: timedelta) -> str:
        """Format timedelta as WebVTT timestamp."""
        total_seconds = int(td.total_seconds())
        milliseconds = td.microseconds // 1000
        
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"
    
    def _parse_style_block(self, lines, start_idx):
        """Parse a STYLE block and return (style_content, next_index)."""
        style_lines = []
        i = start_idx
        
        while i < len(lines):
            line = lines[i].strip()
            
            # End of style block (blank line or new block)
            if not line or self._STYLE_BLOCK_START.match(line) or self._NOTE_BLOCK_START.match(line):
                break
            
            style_lines.append(lines[i])  # Preserve original formatting
            i += 1
        
        return '\n'.join(style_lines) if style_lines else None, i
    
    def _skip_note_block(self, lines, start_idx):
        """Skip a NOTE block and return next index."""
        i = start_idx
        
        while i < len(lines):
            line = lines[i].strip()
            
            # End of note block (blank line or new block)
            if not line:
                break
            
            i += 1
        
        return i
    
    def _extract_speaker_name(self, text: str) -> str|None:
        """Extract speaker name from voice tags."""
        match = self._VOICE_TAG_PATTERN.search(text)
        if match:
            return match.group(1).strip()
        return None
    
    def _process_vtt_text(self, text: str) -> str:
        """Process VTT text for internal representation, preserving HTML tags."""
        if not text:
            return ""
        
        # Remove voice tags but preserve the content
        # <v Speaker>text</v> -> text, <v.class Speaker>text -> text
        text = self._VOICE_TAG_PATTERN.sub('', text)
        text = self._CLOSING_VOICE_TAG_PATTERN.sub('', text)
        
        # WebVTT supports HTML tags natively, so preserve them
        return text.strip()
    
    def _restore_vtt_text(self, text: str, metadata: dict) -> str:
        """Restore VTT text for output, adding back voice tags if needed."""
        if not text:
            return ""
        
        # Add voice tags back if speaker is present
        speaker = metadata.get('speaker')
        if speaker:
            return f"<v {speaker}>{text}</v>"
        
        return text