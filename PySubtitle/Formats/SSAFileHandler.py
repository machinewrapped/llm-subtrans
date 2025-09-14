import pysubs2
import pysubs2.time
import regex
from datetime import timedelta
from typing import TextIO

from PySubtitle.Helpers.Color import Color
from PySubtitle.SubtitleFileHandler import (
    SubtitleFileHandler,
    default_encoding,
    fallback_encoding,
)
from PySubtitle.SubtitleLine import SubtitleLine
from PySubtitle.SubtitleData import SubtitleData
from PySubtitle.SubtitleError import SubtitleParseError
from PySubtitle.Helpers.Localization import _

# Precompiled regex patterns for performance
_START_TAGS_PATTERN = regex.compile(r'^(\{[^}]*\})+')
_TAG_BLOCK_PATTERN = regex.compile(r'\{[^}]+\}')
_STANDALONE_BASIC_TAG_PATTERN = regex.compile(r'^\{\\(?:[ibs][01]|u[01]?)\}$')
# Matches SSA basic formatting tags: italic (\i1, \i0), bold (\b1, \b0), strikeout (\s1, \s0), underline (\u1, \u0)
_BASIC_TAG_PATTERN = regex.compile(r'\\(?:[ibs][01]|u[01]?)')

# Precompiled SSA to HTML conversion patterns
_SSA_TO_HTML_PATTERNS = [
    (regex.compile(r'{\\i1}'), '<i>'),
    (regex.compile(r'{\\i0}'), '</i>'),
    (regex.compile(r'{\\b1}'), '<b>'),
    (regex.compile(r'{\\b0}'), '</b>'),
    (regex.compile(r'{\\u1}'), '<u>'),
    (regex.compile(r'{\\u0}'), '</u>'),
    (regex.compile(r'{\\s1}'), '<s>'),
    (regex.compile(r'{\\s0}'), '</s>')
]

# Precompiled HTML to SSA conversion patterns
_HTML_TO_SSA_PATTERNS = [
    (regex.compile(r'<i>'), r'{\\i1}'),
    (regex.compile(r'</i>'), r'{\\i0}'),
    (regex.compile(r'<b>'), r'{\\b1}'),
    (regex.compile(r'</b>'), r'{\\b0}'),
    (regex.compile(r'<u>'), r'{\\u1}'),
    (regex.compile(r'</u>'), r'{\\u0}'),
    (regex.compile(r'<s>'), r'{\\s1}'),
    (regex.compile(r'</s>'), r'{\\s0}')
]


class SSAFileHandler(SubtitleFileHandler):
    """
    File handler for Advanced SubStation Alpha (SSA/ASS) subtitle format using pysubs2 library.

    Supports reading and writing SSA/ASS with file- and line-level metadata.
    """
    
    SUPPORTED_EXTENSIONS = {'.ass': 10, '.ssa': 10}

    def load_file(self, path: str) -> SubtitleData:
        # TEST: Use .ssa extension as format hint to detect Marked lines ... this causes more problems than it fixes, let's trust pysubs2
        # format_hint = 'ssa' if path.lower().endswith('.ssa') else None
        format_hint = None
        
        try:
            subs: pysubs2.SSAFile = pysubs2.SSAFile.load(path, encoding=default_encoding, format_=format_hint)
            return self._parse_subs(subs)
        except UnicodeDecodeError:
            subs: pysubs2.SSAFile = pysubs2.SSAFile.load(path, encoding=fallback_encoding, format_=format_hint, newline='')
            return self._parse_subs(subs)
        except Exception as e:
            raise e if isinstance(e, SubtitleParseError) else SubtitleParseError(_("Failed to parse subtitles: {}" ).format(str(e)), e)
    
    def parse_file(self, file_obj: TextIO) -> SubtitleData:
        """
        Parse file content and return SubtitleData with lines and metadata.
        """
        try:
            subs : pysubs2.SSAFile = pysubs2.SSAFile.from_file(file_obj)
            return self._parse_subs(subs)
                
        except UnicodeDecodeError:
            raise  # Re-raise UnicodeDecodeError for fallback handling
        except Exception as e:
            raise SubtitleParseError(_("Failed to parse file: {}").format(str(e)), e)

    def parse_string(self, content: str) -> SubtitleData:
        """
        Parse string content and return SubtitleData with lines and metadata.
        """
        try:
            subs = pysubs2.SSAFile.from_string(content)
            return self._parse_subs(subs)
                
        except Exception as e:
            raise SubtitleParseError(_("Failed to parse content: {}").format(str(e)), e)
    
    def compose(self, data: SubtitleData) -> str:
        """
        Compose subtitle lines into SSA/ASS format string using metadata.
        
        Args:
            data: SubtitleData containing lines and file metadata
            
        Returns:
            str: formatted subtitle content
        """
        subs : pysubs2.SSAFile = pysubs2.SSAFile()
        subs.info["TranslatedBy"] = "LLM-Subtrans"

        self._build_metadata(subs, data.metadata)

        # Restore original detected format
        file_format = data.metadata.get('pysubs2_format', 'ass')

        # Convert SubtitleLines to pysubs2 format
        for line in data.lines:
            if line.text and line.start is not None and line.end is not None:
                pysubs2_line = self._subtitle_line_to_pysubs2(line)
                subs.append(pysubs2_line)
        
        return subs.to_string(file_format)
    
    def _parse_subs(self, subs : pysubs2.SSAFile):
        """
        Convert pysubs2 subtitles to SubtitleLines, adding an index
        """
        try:
            file_format : str = getattr(subs, "format", "ass")

            lines : list[SubtitleLine] = []
            for index, line in enumerate(subs, 1):
                lines.append(self._pysubs2_to_subtitle_line(line, index))

            # Extract serializable metadata
            metadata = self._parse_metadata(subs, file_format)

            detected_format : str = pysubs2.formats.get_file_extension(file_format)

            return SubtitleData(lines=lines, metadata=metadata, detected_format=detected_format)

        except Exception as e:
            raise SubtitleParseError(_("Failed to parse subtitles: {}" ).format(str(e)), e)
        
    def _pysubs2_to_subtitle_line(self, pysubs2_line: pysubs2.SSAEvent, index: int) -> SubtitleLine:
        """Convert pysubs2 SSAEvent to SubtitleLine with metadata preservation."""
        
        start = timedelta(milliseconds=pysubs2_line.start)
        end = timedelta(milliseconds=pysubs2_line.end)
        
        # Extract text content using .text to preserve inline formatting,
        # then convert SSA tags to HTML for SRT and GUI compatibility
        text = self._ssa_to_html(pysubs2_line.text)
        
        metadata = {
            'style': pysubs2_line.style,
            'layer': pysubs2_line.layer,
            'name': pysubs2_line.name,
            'margin_l': pysubs2_line.marginl,
            'margin_r': pysubs2_line.marginr,
            'margin_v': pysubs2_line.marginv,
            'effect': pysubs2_line.effect,
            'type': pysubs2_line.type,
            'marked': getattr(pysubs2_line, 'marked', False)
        }
        
        # Extract whole-line SSA override tags and store in metadata
        if pysubs2_line.text:
            extracted_tags = self._extract_whole_line_tags(pysubs2_line.text)
            if extracted_tags:
                metadata.update(extracted_tags)
        
        return SubtitleLine.Construct(
            number=index,
            start=start,
            end=end,
            text=text,
            metadata=metadata
        )
    
    def _subtitle_line_to_pysubs2(self, line: SubtitleLine) -> pysubs2.SSAEvent:
        """
        Convert SubtitleLine back to pysubs2 SSAEvent using preserved metadata.
        """
        event = pysubs2.SSAEvent()
        
        if line.start:
            event.start = pysubs2.time.make_time(s=line.start.total_seconds())
        else:
            event.start = 0
            
        if line.end:
            event.end = pysubs2.time.make_time(s=line.end.total_seconds())
        else:
            event.end = 0
        
        # Convert HTML tags back to SSA tags, then set text directly
        ssa_text = self._html_to_ass(line.text or "")
        
        ssa_text = self._restore_whole_line_tags(ssa_text, line.metadata or {})
        
        event.text = ssa_text
        
        # Restore metadata if available, otherwise use pysubs2 defaults
        if line.metadata:
            event.style = line.metadata.get('style', event.style)
            event.layer = line.metadata.get('layer', event.layer)
            event.name = line.metadata.get('name', event.name)
            event.marginl = line.metadata.get('margin_l', event.marginl)
            event.marginr = line.metadata.get('margin_r', event.marginr)
            event.marginv = line.metadata.get('margin_v', event.marginv)
            event.effect = line.metadata.get('effect', event.effect)
            event.type = line.metadata.get('type', event.type)
            event.marked = line.metadata.get('marked', False)
        
        return event

    def _parse_metadata(self, subs : pysubs2.SSAFile, subtitle_format : str) -> dict:
        """
        Convert pysubs2 metadata to JSON-serializable format.
        Handles Color objects and other pysubs2-specific types.
        """
        # Extract serializable metadata from the pysubs2 file
        metadata = {
            'pysubs2_format': subtitle_format,
            'info': dict(subs.info),  # Script info section
            'aegisub_project': dict(subs.aegisub_project) if hasattr(subs, 'aegisub_project') else {}
        }
        
        styles = {}
        for name, style in subs.styles.items():
            style_dict = style.as_dict()
            
            for field, value in style_dict.items():
                if isinstance(value, pysubs2.Color):
                    style_dict[field] = Color(value.r, value.g, value.b, value.a)
            
            styles[name] = style_dict
        
        metadata['styles'] = styles
        return metadata
    
    def _build_metadata(self, subs : pysubs2.SSAFile, metadata : dict) -> None:
        """
        Restore pysubs2 metadata from JSON-serialized format.
        Converts Color dicts back to pysubs2.Color objects.
        """
        # Restore script info from metadata
        if 'info' in metadata:
            subs.info.update(metadata['info'])

        if 'Title' in metadata:
            subs.info['Title'] = metadata['Title']
        
        if 'Language' in metadata:
            subs.info['Language'] = metadata['Language']

        # Restore styles from metadata
        if 'styles' in metadata:
            # Clear default styles that pysubs2 creates automatically to avoid conflicts
            subs.styles.clear()
            
            for style_name, style_fields in metadata['styles'].items():
                style_data = style_fields.copy()
                
                for field, value in style_data.items():
                    if isinstance(value, Color):
                        style_data[field] = pysubs2.Color(value.r, value.g, value.b, value.a)
                
                style = pysubs2.SSAStyle(**style_data)
                subs.styles[style_name] = style
        
        # Restore aegisub project data if present
        if 'aegisub_project' in metadata and hasattr(subs, 'aegisub_project'):
            subs.aegisub_project.update(metadata['aegisub_project'])
    
    def _extract_whole_line_tags(self, ssa_text: str) -> dict:
        """Extract whole-line SSA override tags from start of line and return as metadata."""
        if not ssa_text:
            return {}
            
        metadata = {}
        
        # Match consecutive SSA tags at the start of the line
        start_tags_match = _START_TAGS_PATTERN.match(ssa_text)
        if start_tags_match:
            tags_section = start_tags_match.group(0)
            
            # Extract only the complex (non-basic formatting) tags
            complex_tags = []
            for tag_match in _TAG_BLOCK_PATTERN.finditer(tags_section):
                tag = tag_match.group(0)
                # If it's a standalone basic formatting tag, skip it entirely
                if _STANDALONE_BASIC_TAG_PATTERN.match(tag):
                    continue
                
                # For composite tags, remove basic formatting but keep the rest
                cleaned_tag = _BASIC_TAG_PATTERN.sub('', tag)

                if cleaned_tag != '{}':
                    complex_tags.append(cleaned_tag)
            
            if complex_tags:
                metadata['override_tags_start'] = ''.join(complex_tags)
        
        return metadata
    
    def _restore_whole_line_tags(self, text: str, metadata: dict) -> str:
        """Restore whole-line SSA tags from metadata."""
        if 'override_tags_start' in metadata:
            return f"{metadata['override_tags_start']}{text}"
        return text
    
    def _ssa_to_html(self, ssa_text: str) -> str:
        """Convert SSA inline formatting tags to HTML tags for GUI display."""
        if not ssa_text:
            return ""
            
        text = ssa_text
        
        # Remove complex whole-line tags at the start (they'll be stored in metadata)
        # But preserve basic formatting tags for HTML conversion
        start_match = _START_TAGS_PATTERN.match(text)
        if start_match:
            tags_section = start_match.group(0)
            remaining_text = text[len(tags_section):]

            # Extract basic formatting tags from both standalone blocks and composite blocks
            basic_tags = []
            for tag_match in _TAG_BLOCK_PATTERN.finditer(tags_section):
                tag_content = tag_match.group(0)
                if _STANDALONE_BASIC_TAG_PATTERN.match(tag_content):
                    basic_tags.append(tag_content)
                else:
                    for basic_tag in _BASIC_TAG_PATTERN.finditer(tag_content):
                        basic_tags.append('{' + basic_tag.group(0) + '}')

            # Rebuild text with only basic formatting tags preserved
            text = ''.join(basic_tags) + remaining_text

        # Extract basic tags from composite blocks anywhere in the line
        rebuilt = []
        last_end = 0
        for tag_match in _TAG_BLOCK_PATTERN.finditer(text):
            block = tag_match.group(0)
            rebuilt.append(text[last_end:tag_match.start()])

            if _STANDALONE_BASIC_TAG_PATTERN.match(block):
                rebuilt.append(block)
            else:
                basic_tags = ['{' + m.group(0) + '}' for m in _BASIC_TAG_PATTERN.finditer(block)]
                cleaned = _BASIC_TAG_PATTERN.sub('', block)
                if cleaned != '{}':
                    rebuilt.append(cleaned)
                rebuilt.extend(basic_tags)

            last_end = tag_match.end()

        rebuilt.append(text[last_end:])
        text = ''.join(rebuilt)
        
        # Convert line breaks:
        # \N (hard line break) -> \n (newline for GUI)
        # \n (soft line break) -> <wbr> (word break opportunity)
        text = text.replace('\\N', '\n')
        text = text.replace('\\n', '<wbr>')
        
        for pattern, replacement in _SSA_TO_HTML_PATTERNS:
            text = pattern.sub(replacement, text)
        
        # For any remaining SSA tags that aren't basic formatting, preserve them
        # This allows translators to see and preserve complex inline formatting
        # (colors, fonts, etc.) that don't have HTML equivalents
        
        return text
    
    def _html_to_ass(self, html_text: str) -> str:
        """Convert HTML tags back to SSA inline formatting tags."""
        if not html_text:
            return ""
            
        text = html_text
        
        # Convert line breaks back:
        # \n (newline from GUI) -> \N (hard line break)
        # <wbr> (word break opportunity) -> \n (soft line break)
        text = text.replace('<wbr>', '\\n')
        text = text.replace('\n', '\\N')
        
        for pattern, replacement in _HTML_TO_SSA_PATTERNS:
            text = pattern.sub(replacement, text)
        
        # Preserve any other HTML that might be part of the dialogue content
        # (e.g., someone translating a movie about HTML)
        
        return text

