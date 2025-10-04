import os
import tempfile
import unittest
from typing import TextIO
from unittest.mock import MagicMock, patch

from PySubtrans.SubtitleFileHandler import SubtitleFileHandler
from PySubtrans.SubtitleFormatRegistry import SubtitleFormatRegistry
from PySubtrans.Formats.SrtFileHandler import SrtFileHandler
from PySubtrans.SubtitleData import SubtitleData
from PySubtrans.SubtitleError import SubtitleParseError
from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Helpers.Tests import (
    log_input_expected_error,
    skip_if_debugger_attached,
)


class DummySrtHandler(SubtitleFileHandler):
    SUPPORTED_EXTENSIONS = {'.srt': 5}

    def parse_file(self, file_obj : TextIO) -> SubtitleData:
        return SubtitleData(lines=[], metadata={})

    def parse_string(self, content : str) -> SubtitleData:
        return SubtitleData(lines=[], metadata={})

    def compose(self, data : SubtitleData) -> str:
        return ""

    def load_file(self, path: str) -> SubtitleData:
        return self.parse_string("")


class TestSubtitleFormatRegistry(LoggedTestCase):
    def setUp(self) -> None:
        super().setUp()
        SubtitleFormatRegistry.clear()
        SubtitleFormatRegistry.discover()

    def test_AutoDiscovery(self):
        handler = SubtitleFormatRegistry.get_handler_by_extension('.srt')
        self.assertLoggedIs(".srt handler", SrtFileHandler, handler)

    @skip_if_debugger_attached
    def test_UnknownExtension(self):
        with self.assertRaises(ValueError) as e:
            SubtitleFormatRegistry.get_handler_by_extension('.unknown')
        log_input_expected_error('.unknown', ValueError, e.exception)

    def test_EnumerateFormats(self):
        formats = SubtitleFormatRegistry.enumerate_formats()
        self.assertLoggedIn('contains .srt', '.srt', formats)

    def test_CreateHandler(self):
        handler = SubtitleFormatRegistry.create_handler('.srt')
        self.assertLoggedIsInstance('.srt handler instance', handler, SrtFileHandler)

    def test_DuplicateRegistrationPriority(self):

        SubtitleFormatRegistry.disable_autodiscovery()

        SubtitleFormatRegistry.register_handler(DummySrtHandler)
        handler = SubtitleFormatRegistry.get_handler_by_extension('.srt')
        self.assertLoggedIs('priority', DummySrtHandler, handler)

        SubtitleFormatRegistry.register_handler(SrtFileHandler)
        handler_after = SubtitleFormatRegistry.get_handler_by_extension('.srt')
        self.assertLoggedIs('priority restored', SrtFileHandler, handler_after)

        SubtitleFormatRegistry.clear()

    def test_CreateHandlerWithFilename(self):
        handler = SubtitleFormatRegistry.create_handler(filename="test.srt")
        self.assertLoggedIsInstance('test.srt handler instance', handler, SrtFileHandler)

    @skip_if_debugger_attached
    def test_CreateHandlerWithNoExtensionOrFilename(self):
        with self.assertRaises(ValueError) as e:
            SubtitleFormatRegistry.create_handler()
        log_input_expected_error("None", ValueError, e.exception)

    @skip_if_debugger_attached
    def test_CreateHandlerWithEmptyExtension(self):
        with self.assertRaises(ValueError) as e:
            SubtitleFormatRegistry.create_handler(extension="")
        log_input_expected_error('""', ValueError, e.exception)

    @skip_if_debugger_attached
    def test_CreateHandlerWithInvalidFilename(self):
        with self.assertRaises(ValueError) as e:
            SubtitleFormatRegistry.create_handler(filename="test")
        log_input_expected_error("test", ValueError, e.exception)

    def test_ListAvailableFormats(self):
        formats = SubtitleFormatRegistry.list_available_formats()
        self.assertLoggedIn('contains .srt', '.srt', formats)
        self.assertIsInstance(formats, str)

    def test_ListAvailableFormatsEmpty(self):
        SubtitleFormatRegistry.disable_autodiscovery()
        formats = SubtitleFormatRegistry.list_available_formats()
        self.assertLoggedEqual('empty registry', 'None', formats)
        SubtitleFormatRegistry.discover()

    def test_GetFormatFromFilename(self):
        
        extension = SubtitleFormatRegistry.get_format_from_filename("test.srt")
        self.assertLoggedEqual('test.srt extension', '.srt', extension)

        extension = SubtitleFormatRegistry.get_format_from_filename("test.SRT")
        self.assertLoggedEqual('test.SRT extension', '.srt', extension)

        extension = SubtitleFormatRegistry.get_format_from_filename("test")
        self.assertLoggedIsNone('test extension', extension)
        
        extension = SubtitleFormatRegistry.get_format_from_filename("path/to/file.vtt")
        self.assertLoggedEqual('path/to/file.vtt extension', '.vtt', extension)

    def test_DetectFormatAndLoadFile(self):
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.srt', delete=False, encoding='utf-8') as f:
            f.write("1\n00:00:01,000 --> 00:00:02,000\nTest subtitle\n")
            temp_path = f.name
        
        try:
            data = SubtitleFormatRegistry.detect_format_and_load_file(temp_path)
            self.assertLoggedIn('metadata has detected_format', 'detected_format', data.metadata)
            self.assertIsInstance(data, SubtitleData)
        finally:
            os.unlink(temp_path)

    @patch('pysubs2.load')
    @skip_if_debugger_attached
    def test_DetectFormatAndLoadFileError(self, mock_load):
        mock_load.side_effect = Exception("Parse error")

        with self.assertRaises(SubtitleParseError) as e:
            SubtitleFormatRegistry.detect_format_and_load_file("nonexistent.srt")
        log_input_expected_error("nonexistent.srt", SubtitleParseError, e.exception)

    @patch('pysubs2.load')
    @skip_if_debugger_attached
    def test_DetectFormatAndLoadFileUnicodeError(self, mock_load):
        
        mock_subs = MagicMock()
        mock_subs.format = "srt"
        
        mock_load.side_effect = [UnicodeDecodeError('utf-8', b'', 0, 1, 'invalid'), mock_subs]
        
        with patch.object(SubtitleFormatRegistry, 'create_handler') as mock_create:
            mock_handler = MagicMock()
            mock_handler.load_file.return_value = SubtitleData(lines=[], metadata={})
            mock_create.return_value = mock_handler
            
            data = SubtitleFormatRegistry.detect_format_and_load_file("test.srt")
            self.assertLoggedEqual('fallback encoding used', 2, mock_load.call_count)
            self.assertIsInstance(data, SubtitleData)

    def test_ClearMethod(self):
        
        SubtitleFormatRegistry.discover()
        formats_before = len(SubtitleFormatRegistry.enumerate_formats())
        self.assertLoggedGreater('formats before clear', formats_before, 0)

        SubtitleFormatRegistry.disable_autodiscovery()
        formats_after = len(SubtitleFormatRegistry.enumerate_formats())
        self.assertLoggedEqual('formats after clear', 0, formats_after)
        
        SubtitleFormatRegistry.discover()

    def test_DiscoverMethod(self):
        
        SubtitleFormatRegistry.disable_autodiscovery()
        formats_before = len(SubtitleFormatRegistry.enumerate_formats())
        self.assertLoggedEqual('formats before discover', 0, formats_before)

        SubtitleFormatRegistry.discover()
        formats_after = len(SubtitleFormatRegistry.enumerate_formats())
        self.assertLoggedGreater('formats after discover', formats_after, 0)

    def test_EnsureDiscoveredBehavior(self):
        
        SubtitleFormatRegistry.disable_autodiscovery()
        formats_before = len(SubtitleFormatRegistry._handlers)
        self.assertLoggedEqual('handlers before access', 0, formats_before)

        SubtitleFormatRegistry.enable_autodiscovery()
        formats = SubtitleFormatRegistry.enumerate_formats()
        formats_after = len(SubtitleFormatRegistry._handlers)
        self.assertLoggedGreater('handlers after access', formats_after, 0)

        self.assertLoggedGreater('formats list non-empty', len(formats), 0)

        self.assertLoggedTrue('discovered flag', SubtitleFormatRegistry._discovered)

    def test_RegisterHandlerWithLowerPriority(self):
        
        class LowerPrioritySrtHandler(SubtitleFileHandler):
            SUPPORTED_EXTENSIONS = {'.srt': 1}
            
            def parse_file(self, file_obj : TextIO) -> SubtitleData:
                return SubtitleData(lines=[], metadata={})
            
            def parse_string(self, content : str) -> SubtitleData:
                return SubtitleData(lines=[], metadata={})
            
            def compose(self, data : SubtitleData) -> str:
                return ""
            
            def load_file(self, path: str) -> SubtitleData:
                return self.parse_string("")
        
        SubtitleFormatRegistry.disable_autodiscovery()
        SubtitleFormatRegistry.register_handler(SrtFileHandler)
        handler_before = SubtitleFormatRegistry.get_handler_by_extension('.srt')
        self.assertLoggedIs('before lower priority', SrtFileHandler, handler_before)
        
        SubtitleFormatRegistry.register_handler(LowerPrioritySrtHandler)
        handler_after = SubtitleFormatRegistry.get_handler_by_extension('.srt')
        self.assertLoggedIs('after lower priority', SrtFileHandler, handler_after)
        
        SubtitleFormatRegistry.clear()

    def test_CaseInsensitiveExtensions(self):
        
        handler_lower = SubtitleFormatRegistry.get_handler_by_extension('.srt')
        handler_upper = SubtitleFormatRegistry.get_handler_by_extension('.SRT')
        handler_mixed = SubtitleFormatRegistry.get_handler_by_extension('.Srt')

        self.assertLoggedIs('lower vs upper handler', handler_lower, handler_upper)
        self.assertLoggedIs('upper vs mixed handler', handler_upper, handler_mixed)

    def test_DisableAutodiscovery(self):
        
        SubtitleFormatRegistry.discover()
        formats_before = len(SubtitleFormatRegistry.enumerate_formats())
        self.assertLoggedGreater('formats before disable', formats_before, 0)

        SubtitleFormatRegistry.disable_autodiscovery()
        formats_after = len(SubtitleFormatRegistry.enumerate_formats())
        discovered_flag = SubtitleFormatRegistry._discovered

        self.assertLoggedEqual('formats after disable', 0, formats_after)
        self.assertLoggedTrue('discovered flag after disable', discovered_flag)
        
        SubtitleFormatRegistry.discover()

    def test_EnableAutodiscovery(self):
        
        SubtitleFormatRegistry.disable_autodiscovery()
        discovered_flag_before = SubtitleFormatRegistry._discovered
        self.assertLoggedTrue('discovered flag before enable', discovered_flag_before)

        SubtitleFormatRegistry.enable_autodiscovery()
        discovered_flag_after = SubtitleFormatRegistry._discovered
        self.assertLoggedFalse('discovered flag after enable', discovered_flag_after)
        
        SubtitleFormatRegistry.discover()

    def test_DoubleDiscoveryBehavior(self):
        
        SubtitleFormatRegistry.clear()
        SubtitleFormatRegistry.discover()
        handlers_after_first = SubtitleFormatRegistry._handlers.copy()
        priorities_after_first = SubtitleFormatRegistry._priorities.copy()

        SubtitleFormatRegistry.discover()
        handlers_after_second = SubtitleFormatRegistry._handlers.copy()
        priorities_after_second = SubtitleFormatRegistry._priorities.copy()

        self.assertLoggedEqual(
            'handlers unchanged after double discovery',
            handlers_after_first,
            handlers_after_second,
        )
        
        self.assertLoggedEqual(
            'priorities unchanged after double discovery',
            priorities_after_first,
            priorities_after_second,
        )

    # Phase 6: Enhanced Format Detection Tests
    def test_DetectSrtFormatWithTxtExtension(self):
        
        srt_content = "1\n00:00:01,000 --> 00:00:02,000\nTest subtitle\n\n2\n00:00:03,000 --> 00:00:04,000\nAnother line\n"
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
            f.write(srt_content)
            temp_path = f.name
        
        try:
            data = SubtitleFormatRegistry.detect_format_and_load_file(temp_path)
            detected_format = data.metadata.get('detected_format')
            self.assertLoggedEqual('detected .srt format', '.srt', detected_format)
            lines_count = len(data.lines)
            self.assertLoggedGreater('srt lines count', lines_count, 0)
        finally:
            os.unlink(temp_path)

    def test_DetectAssFormatWithTxtExtension(self):
        
        ass_content = """[Script Info]
Title: Test
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColor, SecondaryColor, OutlineColor, BackColor, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,Test subtitle
Dialogue: 0,0:00:03.00,0:00:04.00,Default,,0,0,0,,Another line
"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
            f.write(ass_content)
            temp_path = f.name
        
        try:
            data = SubtitleFormatRegistry.detect_format_and_load_file(temp_path)
            detected_format = data.metadata.get('detected_format')
            self.assertLoggedEqual('detected .ass format', '.ass', detected_format)
            lines_count = len(data.lines)
            self.assertLoggedGreater('ass lines count', lines_count, 0)
        finally:
            os.unlink(temp_path)

    def test_DetectSsaFormatWithAssExtension(self):
        
        ssa_content = """[Script Info]
Title: Test SSA
ScriptType: v4.00

[V4 Styles]
Format: Name, Fontname, Fontsize, PrimaryColor, SecondaryColor, TertiaryColor, BackColor, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, AlphaLevel, Encoding
Style: Default,Arial,20,65535,255,0,0,0,0,1,2,0,2,10,10,10,0,1

[Events]
Format: Marked, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: Marked=0,0:00:01.00,0:00:02.00,Default,,0,0,0,,Test subtitle
Dialogue: Marked=0,0:00:03.00,0:00:04.00,Default,,0,0,0,,Another line
"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.ass', delete=False, encoding='utf-8') as f:
            f.write(ssa_content)
            temp_path = f.name
        
        try:
            data = SubtitleFormatRegistry.detect_format_and_load_file(temp_path)
            # SSA files are correctly detected as .ssa by pysubs2
            detected_format = data.metadata.get('detected_format')
            self.assertLoggedEqual('detected .ssa format', '.ssa', detected_format)
            lines_count = len(data.lines)
            self.assertLoggedGreater('ssa lines count', lines_count, 0)
        finally:
            os.unlink(temp_path)

    @skip_if_debugger_attached
    def test_FormatDetectionWithMalformedFile(self):
        
        malformed_content = "This is not a valid subtitle file\nJust random text\nWith no format\n"
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
            f.write(malformed_content)
            temp_path = f.name
        
        try:
            with self.assertRaises(SubtitleParseError) as e:
                SubtitleFormatRegistry.detect_format_and_load_file(temp_path)
            log_input_expected_error("malformed file content", SubtitleParseError, e.exception)
            # Verify the error message is user-friendly
            error_msg = str(e.exception)
            self.assertLoggedTrue(
                'error message references format',
                'format' in error_msg.lower(),
                input_value=error_msg,
            )
        finally:
            os.unlink(temp_path)

    @skip_if_debugger_attached
    def test_FormatDetectionWithEmptyFile(self):
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
            f.write("")  # Empty file
            temp_path = f.name
        
        try:
            with self.assertRaises(SubtitleParseError) as e:
                SubtitleFormatRegistry.detect_format_and_load_file(temp_path)
            log_input_expected_error("empty file content", SubtitleParseError, e.exception)
        finally:
            os.unlink(temp_path)

    @skip_if_debugger_attached
    def test_FormatDetectionWithBinaryFile(self):
        
        # Create a binary file that's definitely not a subtitle
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.txt', delete=False) as f:
            f.write(b'\x00\x01\x02\x03\x04\x05\xFF\xFE')  # Binary data
            temp_path = f.name
        
        try:
            with self.assertRaises(SubtitleParseError) as e:
                SubtitleFormatRegistry.detect_format_and_load_file(temp_path)
            log_input_expected_error("binary file content", SubtitleParseError, e.exception)
        finally:
            os.unlink(temp_path)

    def test_FormatDetectionPreservesOriginalMetadata(self):
        
        # Use ASS format since it has rich metadata
        ass_content = """[Script Info]
Title: Test Movie
ScriptType: v4.00+
WrapStyle: 0
Collisions: Normal
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColor, SecondaryColor, OutlineColor, BackColor, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,Test subtitle
"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.unknown', delete=False, encoding='utf-8') as f:
            f.write(ass_content)
            temp_path = f.name
        
        try:
            data = SubtitleFormatRegistry.detect_format_and_load_file(temp_path)
            detected_format = data.metadata.get('detected_format')
            self.assertLoggedEqual('detected .ass format', '.ass', detected_format)
            # Check that original metadata from SSA file is preserved
            self.assertLoggedIn("metadata includes 'info'", 'info', data.metadata)
            script_info = data.metadata['info']
            title = script_info.get('Title')
            self.assertLoggedEqual("script_info['Title']", 'Test Movie', title)
        finally:
            os.unlink(temp_path)

    @skip_if_debugger_attached
    def test_FormatDetectionNonexistentFile(self):
        
        filename = "nonexistent_file.txt"
        with self.assertRaises(SubtitleParseError) as e:
            SubtitleFormatRegistry.detect_format_and_load_file(filename)
        log_input_expected_error(f"filename={filename}", SubtitleParseError, e.exception)

    @skip_if_debugger_attached
    def test_FormatDetectionWithNonUtf8SrtFile(self):
        
        # SRT content with non-ASCII characters (French accents)
        srt_content = "1\n00:00:01,000 --> 00:00:02,000\nCafé à Paris\n\n2\n00:00:03,000 --> 00:00:04,000\nHôtel très cher\n"
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='iso-8859-1') as f:
            f.write(srt_content)
            temp_path = f.name
        
        try:
            data = SubtitleFormatRegistry.detect_format_and_load_file(temp_path)
            detected_format = data.metadata.get('detected_format')
            self.assertLoggedEqual('detected .srt format', '.srt', detected_format)
            lines_count = len(data.lines)
            self.assertLoggedGreater('srt lines count (non-utf)', lines_count, 0)
            # Verify content was loaded correctly
            first_line_text = data.lines[0].text if data.lines else ""
            self.assertLoggedEqual('first line text', 'Café à Paris', first_line_text)
        finally:
            os.unlink(temp_path)

    @skip_if_debugger_attached
    def test_FormatDetectionWithNonUtf8AssFile(self):
        
        # ASS content with non-ASCII characters
        ass_content = """[Script Info]
Title: Test with accents
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColor, SecondaryColor, OutlineColor, BackColor, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,Café à Paris
Dialogue: 0,0:00:03.00,0:00:04.00,Default,,0,0,0,,Hôtel très cher
"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='iso-8859-1') as f:
            f.write(ass_content)
            temp_path = f.name
        
        try:
            data = SubtitleFormatRegistry.detect_format_and_load_file(temp_path)
            detected_format = data.metadata.get('detected_format')
            self.assertLoggedEqual('detected .ass format (non-utf)', '.ass', detected_format)
            lines_count = len(data.lines)
            self.assertLoggedGreater('ass lines count (non-utf)', lines_count, 0)
            # Verify content was loaded correctly
            first_line_text = data.lines[0].text if data.lines else ""
            self.assertLoggedEqual('first line text (ass)', 'Café à Paris', first_line_text)
        finally:
            os.unlink(temp_path)



if __name__ == '__main__':
    unittest.main()
