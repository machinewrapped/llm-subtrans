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
    _TIMESTAMP_PATTERN = regex.compile(
        r'(?:(\d{2,}):)?(\d{2}):(\d{2})\.(\d{3})\s*-->\s*(?:(\d{2,}):)?(\d{2}):(\d{2})\.(\d{3})(.*)'
    )
    _VOICE_TAG_PATTERN = regex.compile(r'^\s*<v((?:\.[\w-]+)*)(?:\s+([^>]+))?>((?:(?!</?v).)*)</v>\s*$')
    _STYLE_BLOCK_START = regex.compile(r'^\s*STYLE\s*$')
    _NOTE_BLOCK_START = regex.compile(r'^\s*NOTE(?:\s.*)?$')

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
            
            if not lines or not lines[0].strip().lstrip('\ufeff').startswith('WEBVTT'):
                raise SubtitleParseError(_("Invalid WebVTT file: missing WEBVTT header"))
            
            file_metadata = self._parse_file_header(lines)
            subtitle_lines = self._parse_cues(lines, file_metadata)
            
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
        
        header_text = data.metadata.get('header_text', 'WEBVTT')
        if '\n' in header_text:
            for header_line in header_text.split('\n'):
                output_lines.append(header_line)
        else:
            output_lines.append(header_text)
        output_lines.append('')
        
        vtt_notes = data.metadata.get('vtt_notes', [])
        for note_block in vtt_notes:
            if not note_block.strip().startswith('NOTE'):
                output_lines.append('NOTE')
                output_lines.append(note_block)
            else:
                output_lines.append(note_block)
            output_lines.append('')
        
        vtt_styles = data.metadata.get('vtt_styles', [])
        for style_block in vtt_styles:
            output_lines.append('STYLE')
            output_lines.append(style_block)
            output_lines.append('')
        
        for line in data.lines:
            if line.text and line.start is not None and line.end is not None:
                if line.metadata and 'cue_id' in line.metadata:
                    output_lines.append(line.metadata['cue_id'])
                
                start_time = self._format_timestamp(line.start)
                end_time = self._format_timestamp(line.end)
                timestamp_line = f"{start_time} --> {end_time}"
                
                if line.metadata and 'vtt_settings' in line.metadata:
                    timestamp_line += f" {line.metadata['vtt_settings']}"
                
                output_lines.append(timestamp_line)
                
                output_text = self._restore_vtt_text(line.text or "", line.metadata or {})
                output_lines.append(output_text)
                output_lines.append('')
        
        return '\n'.join(output_lines)
    
    def _parse_timestamp(self, time_parts) -> timedelta:
        """Parse timestamp components into timedelta."""
        hours, minutes, seconds, milliseconds = [int(p or 0) for p in time_parts]
        return timedelta(hours=hours, minutes=minutes, seconds=seconds, milliseconds=milliseconds)
    
    def _parse_file_header(self, lines: list[str]) -> dict:
        """Parse WebVTT file header including extended headers."""
        header_lines = [lines[0].strip()]
        header_end_idx = 1
        
        while header_end_idx < len(lines):
            line = lines[header_end_idx].strip()
            if not line:
                break
            if not self._is_content_line(line):
                header_lines.append(line)
            else:
                break
            header_end_idx += 1
        
        return {
            'vtt_styles': [],
            'vtt_notes': [],
            'header_text': header_lines[0] if len(header_lines) == 1 else '\n'.join(header_lines),
            '_header_end_idx': header_end_idx
        }
    
    def _is_content_line(self, line: str) -> bool:
        """Check if line looks like content rather than header metadata."""
        return bool(self._TIMESTAMP_PATTERN.match(line) or 
                self._STYLE_BLOCK_START.match(line) or 
                self._NOTE_BLOCK_START.match(line))
    
    def _parse_cues(self, lines: list[str], file_metadata: dict) -> list[SubtitleLine]:
        """Parse all cues from lines starting after header."""
        subtitle_lines = []
        i = file_metadata.pop('_header_end_idx', 1)
        line_number = 1
        
        while i < len(lines):
            line = lines[i].strip()
            
            if not line:
                i += 1
                continue
            
            if self._STYLE_BLOCK_START.match(line):
                style_block, i = self._parse_style_block(lines, i + 1)
                if style_block:
                    file_metadata['vtt_styles'].append(style_block)
                continue
            
            if self._NOTE_BLOCK_START.match(line):
                note_content, i = self._parse_note_block(lines, i)
                if note_content:
                    file_metadata['vtt_notes'].append(note_content)
                continue
            
            cue_line, i = self._parse_single_cue(lines, i, line_number)
            if cue_line:
                subtitle_lines.append(cue_line)
                line_number += 1
            else:
                i += 1
        
        return subtitle_lines
    
    def _parse_single_cue(self, lines: list[str], start_idx: int, line_number: int) -> tuple[SubtitleLine|None, int]:
        """Parse a single cue starting at start_idx."""
        i = start_idx
        cue_id = None
        timestamp_line_idx = i
        
        if i + 1 < len(lines) and self._TIMESTAMP_PATTERN.match(lines[i + 1].strip()):
            cue_id = lines[i].strip()
            timestamp_line_idx = i + 1
        
        if timestamp_line_idx >= len(lines):
            return None, i + 1
            
        timestamp_match = self._TIMESTAMP_PATTERN.match(lines[timestamp_line_idx].strip())
        if not timestamp_match:
            return None, i + 1
        
        start_time = self._parse_timestamp(timestamp_match.groups()[:4])
        end_time = self._parse_timestamp(timestamp_match.groups()[4:8])
        cue_settings = timestamp_match.group(9).strip() if timestamp_match.group(9) else ""
        
        cue_text, next_idx = self._parse_cue_text(lines, timestamp_line_idx + 1)
        processed_text, voice_metadata = self._process_vtt_text(cue_text)
        
        line_metadata = {}
        if cue_id:
            line_metadata['cue_id'] = cue_id
        if cue_settings:
            line_metadata['vtt_settings'] = cue_settings
        line_metadata.update(voice_metadata)
        
        subtitle_line = SubtitleLine.Construct(
            number=line_number,
            start=start_time,
            end=end_time,
            text=processed_text,
            metadata=line_metadata
        )
        
        return subtitle_line, next_idx
    
    def _parse_cue_text(self, lines: list[str], start_idx: int) -> tuple[str, int]:
        """Parse multi-line cue text."""
        cue_text_lines = []
        i = start_idx
        
        while i < len(lines) and lines[i].strip():
            cue_text_lines.append(lines[i])
            i += 1
        
        return '\n'.join(cue_text_lines), i
    
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
            
            if not line or self._STYLE_BLOCK_START.match(line) or self._NOTE_BLOCK_START.match(line):
                break
            
            style_lines.append(lines[i])
            i += 1
        
        return '\n'.join(style_lines) if style_lines else None, i
    
    def _parse_note_block(self, lines, start_idx):
        """Parse a NOTE block and return (note_content, next_index)."""
        note_lines = [lines[start_idx]]
        i = start_idx + 1
        
        while i < len(lines):
            line = lines[i].strip()
            
            if not line or self._STYLE_BLOCK_START.match(line) or self._NOTE_BLOCK_START.match(line):
                break
            
            note_lines.append(lines[i])
            i += 1
        
        return '\n'.join(note_lines) if len(note_lines) > 1 else note_lines[0], i
    
    def _process_vtt_text(self, text: str) -> tuple[str, dict]:
        """Process VTT text and extract metadata for internal representation."""
        if not text:
            return "", {}
        
        metadata = {}
        processed_text = text
        
        # Only process voice tags that wrap the entire line
        voice_match = self._VOICE_TAG_PATTERN.match(processed_text)
        if voice_match:
            css_classes, speaker_name, voice_content = voice_match.groups()
            
            if css_classes:
                classes = css_classes[1:].split('.') if css_classes.startswith('.') else []
                metadata['voice_classes'] = classes
            
            if speaker_name:
                metadata['speaker'] = speaker_name.strip()
            
            # Replace with just the content
            processed_text = voice_content
        
        return processed_text.strip(), metadata
    
    def _restore_vtt_text(self, text: str, metadata: dict) -> str:
        """Restore VTT text for output, adding back voice tags."""
        if not text:
            return ""
        
        # Reconstruct voice tag with CSS classes and speaker
        voice_classes = metadata.get('voice_classes', [])
        speaker = metadata.get('speaker', '')
        
        if voice_classes or speaker:
            tag_parts = '.'.join(['v'] + voice_classes)
            speaker_part = f' {speaker}' if speaker else ''
            return f"<{tag_parts}{speaker_part}>{text}</v>"
        else:
            return text
