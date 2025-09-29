import unittest
from datetime import timedelta
import tempfile
import os

from PySubtrans.Formats.SSAFileHandler import SSAFileHandler
from PySubtrans.SubtitleLine import SubtitleLine
from PySubtrans.SubtitleData import SubtitleData
from PySubtrans.SubtitleError import SubtitleParseError
from PySubtrans.Helpers.Tests import (
    log_info,
    log_input_expected_result,
    log_test_name,
    skip_if_debugger_attached_decorator,
)

class TestSSAFileHandler(unittest.TestCase):
    """Test cases for SSA file handler."""
    
    def setUp(self) -> None:
        """Set up test fixtures."""
        log_test_name(self._testMethodName)
        self.handler = SSAFileHandler()
        
        # Sample SSA content for testing
        self.sample_ssa_content = """[Script Info]
Title: Test Subtitles
ScriptType: v4.00+
PlayDepth: 0
ScaledBorderAndShadow: Yes
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,50,&H00FFFFFF,&H0000FFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,30,30,30,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.50,0:00:03.00,Default,,0,0,0,,First subtitle line
Dialogue: 0,0:00:04.00,0:00:06.50,Default,,0,0,0,,Second subtitle line\\Nwith line break
Dialogue: 0,0:00:07.00,0:00:09.00,Default,,0,0,0,,Third subtitle line
"""
        
        # Expected parsed lines
        self.expected_lines = [
            SubtitleLine.Construct(
                number=1,
                start=timedelta(seconds=1, milliseconds=500),
                end=timedelta(seconds=3),
                text="First subtitle line",
                metadata={
                    'layer': 0,
                    'style': 'Default',
                    'name': '',
                    'margin_l': 0,
                    'margin_r': 0,
                    'margin_v': 0,
                    'effect': ''
                }
            ),
            SubtitleLine.Construct(
                number=2,
                start=timedelta(seconds=4),
                end=timedelta(seconds=6, milliseconds=500),
                text="Second subtitle line\nwith line break",
                metadata={
                    'layer': 0,
                    'style': 'Default',
                    'name': '',
                    'margin_l': 0,
                    'margin_r': 0,
                    'margin_v': 0,
                    'effect': ''
                }
            ),
            SubtitleLine.Construct(
                number=3,
                start=timedelta(seconds=7),
                end=timedelta(seconds=9),
                text="Third subtitle line",
                metadata={
                    'layer': 0,
                    'style': 'Default',
                    'name': '',
                    'margin_l': 0,
                    'margin_r': 0,
                    'margin_v': 0,
                    'effect': ''
                }
            )
        ]
    
    def test_get_file_extensions(self):
        """Test that the handler returns correct file extensions."""
        
        expected = ['.ass', '.ssa']
        result = self.handler.get_file_extensions()
        
        log_input_expected_result("", expected, result)
        self.assertEqual(result, expected)
    
    def test_parse_string_basic(self):
        """Test parsing of basic SSA content."""
        
        data = self.handler.parse_string(self.sample_ssa_content)
        lines = data.lines
        
        log_input_expected_result(self.sample_ssa_content[:100] + "...", len(self.expected_lines), len(lines))
        
        self.assertEqual(len(lines), len(self.expected_lines))
        
        for i, (expected, actual) in enumerate(zip(self.expected_lines, lines)):
            with self.subTest(line_number=i+1):
                self.assertEqual(actual.number, expected.number)
                self.assertEqual(actual.start, expected.start)
                self.assertEqual(actual.end, expected.end)
                self.assertEqual(actual.text, expected.text)
                self.assertEqual(actual.metadata['style'], expected.metadata['style'])
    
    def test_load_file(self):
        """Test parsing from file path."""

        with tempfile.NamedTemporaryFile('w', delete=False, suffix='.ass', encoding='utf-8') as f:
            f.write(self.sample_ssa_content)
            temp_path = f.name

        try:
            data = self.handler.load_file(temp_path)
        finally:
            os.remove(temp_path)

        lines = data.lines
        log_input_expected_result("File content", 3, len(lines))
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0].text, "First subtitle line")
    
    
    def test_compose_lines_basic(self):
        """Test basic line composition to SSA format."""
        
        lines = [
            SubtitleLine.Construct(
                number=1,
                start=timedelta(seconds=1, milliseconds=500),
                end=timedelta(seconds=3),
                text="Test subtitle",
                metadata={'style': 'Default', 'layer': 0, 'name': '', 
                         'margin_l': 0, 'margin_r': 0, 'margin_v': 0, 'effect': ''}
            )
        ]
        
        data = SubtitleData(lines=lines, metadata={'pysubs2_format': 'ass'})
        result = self.handler.compose(data)
        
        # Log before assertions
        expected_sections = ["[Script Info]", "[V4+ Styles]", "[Events]", "Dialogue: 0,0:00:01.50,0:00:03.00,Default,,0,0,0,,Test subtitle"]
        has_all_sections = all(section in result for section in expected_sections)
        log_input_expected_result("1 line", True, has_all_sections)
        
        # Check that the result contains key SSA sections
        self.assertIn("[Script Info]", result)
        self.assertIn("[V4+ Styles]", result)
        self.assertIn("[Events]", result)
        self.assertIn("Dialogue: 0,0:00:01.50,0:00:03.00,Default,,0,0,0,,Test subtitle", result)
    
    def test_compose_lines_with_line_breaks(self):
        """Test composition with line breaks."""
        
        lines = [
            SubtitleLine.Construct(
                number=1,
                start=timedelta(seconds=1),
                end=timedelta(seconds=3),
                text="First line\nSecond line",
                metadata={'style': 'Default', 'layer': 0, 'name': '', 'margin_l': 0, 'margin_r': 0, 'margin_v': 0, 'effect': ''}
            )
        ]
        
        data = SubtitleData(lines=lines, metadata={'pysubs2_format': 'ass'})
        result = self.handler.compose(data)
        
        # pysubs2 converts newlines back to \\N in SSA format output
        expected_text = "First line\\NSecond line"
        contains_expected = expected_text in result
        log_input_expected_result("Contains SSA line break", True, contains_expected)
        self.assertIn(expected_text, result)
    
    def test_parse_empty_events_section(self):
        """Test parsing SSA file with no events."""
        
        content_no_events = """[Script Info]
Title: Test

[V4+ Styles]
Format: Name, Fontname, Fontsize
Style: Default,Arial,50

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        
        data = self.handler.parse_string(content_no_events)
        lines = data.lines
        
        log_input_expected_result("SSA with no dialogue lines", 0, len(lines))
        self.assertEqual(len(lines), 0)
    
    @skip_if_debugger_attached_decorator
    def test_parse_invalid_ssa_content(self):
        """Test error handling for invalid SSA content."""
        
        invalid_content = """This is not SSA format content"""
        
        assert_raised : bool = True
        with self.assertRaises(SubtitleParseError):
            self.handler.parse_string(invalid_content)
            assert_raised = False
        
        log_input_expected_result("Invalid content", True, assert_raised)
    
    
    def test_round_trip_conversion(self):
        """Test that parsing and composing results in similar content."""
        
        # Parse the sample content
        original_data = self.handler.parse_string(self.sample_ssa_content)
        original_lines = original_data.lines
        
        # Compose back to SSA format using original metadata
        composed = self.handler.compose(original_data)
        
        # Parse the composed content again
        round_trip_data = self.handler.parse_string(composed)
        round_trip_lines = round_trip_data.lines
        
        log_input_expected_result("Original lines", len(original_lines), len(round_trip_lines))
        self.assertEqual(len(original_lines), len(round_trip_lines))
        
        # Validate metadata preservation
        log_input_expected_result("Metadata preserved", True, True)
        self.assertEqual(original_data.metadata['pysubs2_format'], round_trip_data.metadata['pysubs2_format'])
        self.assertIn('styles', original_data.metadata)
        self.assertIn('styles', round_trip_data.metadata)
        self.assertEqual(original_data.metadata['styles'], round_trip_data.metadata['styles'])
        
        # Compare line properties
        for original, round_trip in zip(original_lines, round_trip_lines):
            self.assertEqual(original.start, round_trip.start)
            self.assertEqual(original.end, round_trip.end)
            self.assertEqual(original.text, round_trip.text)

    def test_detect_ssa_format(self):
        """Ensure SSA files retain their format information."""

        sample_ssa = """[Script Info]
ScriptType: v4.00

[V4 Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, TertiaryColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, AlphaLevel, Encoding
Style: Default,Arial,20,16777215,16777215,16777215,0,-1,0,1,2,2,2,10,10,10,0,0

[Events]
Format: Marked, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: Marked=0,0:00:01.00,0:00:02.00,Default,,0000,0000,0000,,SSA line"""

        data = self.handler.parse_string(sample_ssa)
        log_input_expected_result("SSA format", "ssa", data.metadata.get('pysubs2_format'))
        self.assertEqual(data.metadata.get('pysubs2_format'), 'ssa')

        composed = self.handler.compose(data)
        log_input_expected_result("Round trip format", True, "ScriptType: v4.00" in composed)
        self.assertIn("ScriptType: v4.00", composed)
    
    def test_subtitle_line_to_pysubs2_time_conversion(self):
        """Test that _subtitle_line_to_pysubs2 correctly converts timedelta to pysubs2 milliseconds."""
        
        # Test various time formats with precise timedelta values
        test_cases = [
            # (timedelta, expected_milliseconds)
            (timedelta(seconds=1, milliseconds=500), 1500),
            (timedelta(seconds=30), 30000),
            (timedelta(minutes=1, seconds=30, milliseconds=250), 90250),
            (timedelta(hours=1, minutes=23, seconds=45, milliseconds=678), 5025678),
            (timedelta(microseconds=500000), 500),  # 0.5 seconds
        ]
        
        for i, (test_timedelta, expected_ms) in enumerate(test_cases):
            with self.subTest(case=i):
                # Create a test SubtitleLine
                test_line = SubtitleLine.Construct(
                    number=1,
                    start=test_timedelta,
                    end=test_timedelta + timedelta(seconds=2),
                    text="Test",
                    metadata={'style': 'Default', 'layer': 0, 'name': '', 
                             'margin_l': 0, 'margin_r': 0, 'margin_v': 0, 'effect': ''}
                )
                
                # Convert to pysubs2 event
                pysubs2_event = self.handler._subtitle_line_to_pysubs2(test_line)
                
                log_input_expected_result(f"Timedelta {test_timedelta}", expected_ms, pysubs2_event.start)
                self.assertEqual(pysubs2_event.start, expected_ms)
    
    def test_ssa_to_html_formatting_conversion(self):
        """Test SSA tag to HTML conversion."""
        
        # Test cases: (input_ass, expected_html)
        test_cases = [
            ("{\\i1}Italic text{\\i0}", "<i>Italic text</i>"),
            ("{\\b1}Bold text{\\b0}", "<b>Bold text</b>"),
            ("{\\u1}Underlined{\\u0}", "<u>Underlined</u>"),
            ("{\\s1}Strikeout{\\s0}", "<s>Strikeout</s>"),
            ("{\\i1}Mixed {\\b1}formatting{\\b0} here{\\i0}", "<i>Mixed <b>formatting</b> here</i>"),
            ("Normal\\NLine break", "Normal\nLine break"),
            ("Normal\\nSoft break", "Normal<wbr>Soft break"),
            ("No formatting", "No formatting"),
            ("{\\pos(100,200)}Positioned text", "Positioned text"),  # Position removed
            ("{\\c&H00FF00&}Colored text", "Colored text"),  # Color removed
            ("Text {\\c&H00FF00&\\i1}hello{\\i0}", "Text {\\c&H00FF00&}<i>hello</i>"),
        ]
        
        for ssa_input, expected_html in test_cases:
            with self.subTest(input=ssa_input):
                result = self.handler._ssa_to_html(ssa_input)
                log_input_expected_result(ssa_input, expected_html, result)
                self.assertEqual(result, expected_html)
    
    def test_html_to_ssa_formatting_conversion(self):
        """Test HTML tag to SSA conversion."""
        
        # Test cases: (input_html, expected_ass)
        test_cases = [
            ("<i>Italic text</i>", "{\\i1}Italic text{\\i0}"),
            ("<b>Bold text</b>", "{\\b1}Bold text{\\b0}"),
            ("<u>Underlined</u>", "{\\u1}Underlined{\\u0}"),
            ("<s>Strikeout</s>", "{\\s1}Strikeout{\\s0}"),
            ("<i>Mixed <b>formatting</b> here</i>", "{\\i1}Mixed {\\b1}formatting{\\b0} here{\\i0}"),
            ("Normal\nLine break", "Normal\\NLine break"),
            ("Normal<wbr>Soft break", "Normal\\nSoft break"),
            ("No formatting", "No formatting"),
            ("<span>Movie about HTML</span>", "<span>Movie about HTML</span>"),  # Preserve HTML content
            ("Text<wbr>with soft break", "Text\\nwith soft break"),  # wbr preserved
        ]
        
        for html_input, expected_ass in test_cases:
            with self.subTest(input=html_input):
                result = self.handler._html_to_ass(html_input)
                log_input_expected_result(html_input, expected_ass, result)
                self.assertEqual(result, expected_ass)
    
    def test_formatting_round_trip_preservation(self):
        """Test that formatting is preserved through round-trip conversion."""
        
        # Sample SSA content with formatting
        formatted_ssa_content = """[Script Info]
Title: Formatting Test
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,50,&H00FFFFFF,&H0000FFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,30,30,30,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,{\\i1}This is italic text{\\i0}
Dialogue: 0,0:00:04.00,0:00:06.00,Default,,0,0,0,,{\\b1}This is bold{\\b0} and {\\i1}this is italic{\\i0}
Dialogue: 0,0:00:07.00,0:00:09.00,Default,,0,0,0,,Normal text with\\Nline break
"""
        
        # Parse the formatted content
        original_data = self.handler.parse_string(formatted_ssa_content)
        original_lines = original_data.lines
        
        # Verify HTML conversion occurred
        self.assertEqual(len(original_lines), 3)
        
        log_input_expected_result("Italic line", "<i>This is italic text</i>", original_lines[0].text)
        self.assertEqual(original_lines[0].text, "<i>This is italic text</i>")
        
        log_input_expected_result("Mixed formatting", "<b>This is bold</b> and <i>this is italic</i>", original_lines[1].text)
        self.assertEqual(original_lines[1].text, "<b>This is bold</b> and <i>this is italic</i>")
        
        self.assertEqual(original_lines[2].text, "Normal text with\nline break")
        
        # Compose back to SSA
        composed_ass = self.handler.compose(original_data)
        
        # Parse again to test round-trip
        round_trip_data = self.handler.parse_string(composed_ass)
        round_trip_lines = round_trip_data.lines
        
        # Verify formatting preserved
        self.assertEqual(len(round_trip_lines), 3)
        self.assertEqual(round_trip_lines[0].text, "<i>This is italic text</i>")
        self.assertEqual(round_trip_lines[1].text, "<b>This is bold</b> and <i>this is italic</i>")
        self.assertEqual(round_trip_lines[2].text, "Normal text with\nline break")
        
        log_input_expected_result("Round-trip formatting preserved", True, True)
        
        # Verify original SSA tags are in composed output
        log_input_expected_result("SSA tags in output", True, "{\\i1}" in composed_ass and "{\\b1}" in composed_ass)
        self.assertIn("{\\i1}This is italic text{\\i0}", composed_ass)
        self.assertIn("{\\b1}This is bold{\\b0}", composed_ass)
    
    def test_comprehensive_ssa_tag_preservation(self):
        """Test that comprehensive SSA override tags are preserved in metadata."""
        
        # Sample SSA content with various tag types
        complex_ssa_content = """[Script Info]
Title: Complex Tags Test
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,50,&H00FFFFFF,&H0000FFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,30,30,30,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,{\\pos(100,200)\\an5\\fs20}Complex positioned text
Dialogue: 0,0:00:04.00,0:00:06.00,Default,,0,0,0,,{\\pos(50,100)}{\\c&H00FF00&}Multiple tag blocks
Dialogue: 0,0:00:07.00,0:00:09.00,Default,,0,0,0,,Normal text
Dialogue: 0,0:00:10.00,0:00:12.00,Default,,0,0,0,,Text with {\\c&H0000FF&}inline color{\\c}
Dialogue: 0,0:00:13.00,0:00:15.00,Default,,0,0,0,,{\\i1}Italic with {\\b1}bold{\\b0} inside{\\i0}
"""
        
        # Parse the complex content
        data = self.handler.parse_string(complex_ssa_content)
        lines = data.lines
        
        self.assertEqual(len(lines), 5)
        
        # Test complex whole-line tags extraction
        complex_line = lines[0]
        log_input_expected_result("Complex tags extracted", "{\\pos(100,200)\\an5\\fs20}", 
                                complex_line.metadata.get('override_tags_start', ''))
        
        self.assertEqual(complex_line.text, "Complex positioned text")
        self.assertIn('override_tags_start', complex_line.metadata)
        self.assertEqual(complex_line.metadata['override_tags_start'], "{\\pos(100,200)\\an5\\fs20}")
        
        # Test multiple tag blocks
        multi_line = lines[1]
        log_input_expected_result("Multiple blocks extracted", "{\\pos(50,100)}{\\c&H00FF00&}", 
                                multi_line.metadata.get('override_tags_start', ''))
        
        self.assertEqual(multi_line.text, "Multiple tag blocks")
        self.assertIn('override_tags_start', multi_line.metadata)
        self.assertEqual(multi_line.metadata['override_tags_start'], "{\\pos(50,100)}{\\c&H00FF00&}")
        
        # Test normal text unchanged
        normal_line = lines[2]
        log_input_expected_result("Normal text unchanged", "Normal text", normal_line.text)
        
        self.assertEqual(normal_line.text, "Normal text")
        self.assertNotIn('override_tags_start', normal_line.metadata)
        
        # Test inline tags preserved
        inline_line = lines[3]
        self.assertIsNotNone(inline_line)
        if inline_line.text is not None:
            log_input_expected_result("Inline tags preserved", True, 
                                    "{\\c&H0000FF&}" in inline_line.text and "{\\c}" in inline_line.text)
            
            self.assertIn("{\\c&H0000FF&}", inline_line.text)
            self.assertIn("{\\c}", inline_line.text)
            self.assertNotIn('override_tags_start', inline_line.metadata)
        
        # Test mixed HTML and inline SSA tags
        mixed_line = lines[4]
        log_input_expected_result("HTML conversion with inline preservation", 
                                "<i>Italic with <b>bold</b> inside</i>", mixed_line.text)
        
        self.assertEqual(mixed_line.text, "<i>Italic with <b>bold</b> inside</i>")
        self.assertNotIn('override_tags_start', mixed_line.metadata)
        
        # Test round-trip preservation
        composed_ass = self.handler.compose(data)
        round_trip_data = self.handler.parse_string(composed_ass)
        round_trip_lines = round_trip_data.lines
        
        # Verify complex tags restored
        log_input_expected_result("Complex tags restored", True, 
                                "{\\pos(100,200)\\an5\\fs20}" in composed_ass)
        log_input_expected_result("Multi-block tags restored", True, 
                                "{\\pos(50,100)}{\\c&H00FF00&}" in composed_ass)
        
        self.assertIn("{\\pos(100,200)\\an5\\fs20}Complex positioned text", composed_ass)
        self.assertIn("{\\pos(50,100)}{\\c&H00FF00&}Multiple tag blocks", composed_ass)
        
        # Verify round-trip preservation of metadata
        rt_complex = round_trip_lines[0]
        log_input_expected_result("Round-trip metadata preserved", True, 
                                rt_complex.metadata.get('override_tags_start', '') == "{\\pos(100,200)\\an5\\fs20}")
        
        self.assertEqual(rt_complex.text, "Complex positioned text")
        self.assertEqual(rt_complex.metadata.get('override_tags_start', ''), "{\\pos(100,200)\\an5\\fs20}")
    
    def test_tag_extraction_functions(self):
        """Test SSA tag extraction and restoration functions."""
        
        # Test extraction function
        extraction_cases = [
            # Single tag block
            ("{\\pos(100,200)}Text here", {"override_tags_start": "{\\pos(100,200)}"}),
            # Multiple consecutive tags
            ("{\\pos(100,200)\\an5\\fs20}Text", {"override_tags_start": "{\\pos(100,200)\\an5\\fs20}"}),
            # Multiple tag blocks
            ("{\\pos(50,100)}{\\c&H00FF00&}Text", {"override_tags_start": "{\\pos(50,100)}{\\c&H00FF00&}"}),
            # No whole-line tags
            ("Normal text", {}),
            # Inline tags only
            ("Text with {\\c&H0000FF&}color", {}),
        ]
        
        for ssa_input, expected_metadata in extraction_cases:
            with self.subTest(input=ssa_input):
                result = self.handler._extract_whole_line_tags(ssa_input)
                log_input_expected_result(f"Extract: {ssa_input}", expected_metadata, result)
                self.assertEqual(result, expected_metadata)
        
        # Test restoration function
        restoration_cases = [
            # Restore single tag
            ("Text", {"override_tags_start": "{\\pos(100,200)}"}, "{\\pos(100,200)}Text"),
            # Restore complex tags
            ("Text", {"override_tags_start": "{\\pos(100,200)\\an5\\fs20}"}, "{\\pos(100,200)\\an5\\fs20}Text"),
            # No metadata
            ("Text", {}, "Text"),
            # Other metadata present
            ("Text", {"style": "Default", "layer": 0}, "Text"),
        ]
        
        for text_input, metadata, expected_result in restoration_cases:
            with self.subTest(text=text_input, metadata=metadata):
                result = self.handler._restore_whole_line_tags(text_input, metadata)
                log_input_expected_result(f"Restore: {text_input} + {metadata}", expected_result, result)
                self.assertEqual(result, expected_result)
        
        # Test HTML conversion with tag removal
        conversion_cases = [
            # Whole-line tags removed, basic formatting converted
            ("{\\pos(100,200)}{\\i1}Italic text{\\i0}", "<i>Italic text</i>"),
            # Multiple whole-line tags removed
            ("{\\pos(100,200)\\an5\\fs20}Normal text", "Normal text"),
            # Inline tags preserved (non-basic formatting)
            ("Text with {\\c&H0000FF&}color{\\c}", "Text with {\\c&H0000FF&}color{\\c}"),
            # Mixed case
            ("{\\pos(50,100)}Text with {\\c&H00FF00&}inline{\\c} color", "Text with {\\c&H00FF00&}inline{\\c} color"),
        ]
        
        for ssa_input, expected_html in conversion_cases:
            with self.subTest(input=ssa_input):
                result = self.handler._ssa_to_html(ssa_input)
                log_input_expected_result(f"Convert: {ssa_input}", expected_html, result)
                self.assertEqual(result, expected_html)
    
    def test_composite_tags_with_basic_formatting(self):
        """Test that basic formatting tags within composite blocks are preserved."""
        
        # Test cases for composite blocks containing basic formatting
        test_cases = [
            # Composite block with italic
            ("{\\pos(100,200)\\i1}Italic text{\\i0}", "<i>Italic text</i>"),
            # Composite block with bold
            ("{\\pos(50,100)\\b1}Bold text{\\b0}", "<b>Bold text</b>"),
            # Composite block with multiple basic formatting
            ("{\\pos(100,200)\\i1\\b1}Bold italic{\\b0}{\\i0}", "<i><b>Bold italic</b></i>"),
            # Complex composite with color and italic
            ("{\\pos(100,200)\\c&H00FF00&\\i1}Green italic{\\i0}", "<i>Green italic</i>"),
            # Multiple composite blocks
            ("{\\pos(50,100)}{\\c&H00FF00&\\b1}Green bold{\\b0}", "<b>Green bold</b>"),
        ]
        
        for ssa_input, expected_html in test_cases:
            with self.subTest(input=ssa_input):
                result = self.handler._ssa_to_html(ssa_input)
                log_input_expected_result(f"Composite: {ssa_input}", expected_html, result)
                self.assertEqual(result, expected_html)
        
        # Test round-trip preservation with composite tags
        composite_ssa_content = """[Script Info]
Title: Composite Test
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,50,&H00FFFFFF,&H0000FFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,30,30,30,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,{\\pos(100,200)\\i1}Italic positioned text{\\i0}
Dialogue: 0,0:00:04.00,0:00:06.00,Default,,0,0,0,,{\\c&H00FF00&\\b1}Green bold text{\\b0}
"""
        
        # Parse and verify GUI display
        data = self.handler.parse_string(composite_ssa_content)
        lines = data.lines
        
        self.assertEqual(len(lines), 2)
        
        # Verify italic formatting preserved in GUI
        italic_line = lines[0]
        log_input_expected_result("Composite italic in GUI", "<i>Italic positioned text</i>", italic_line.text)
        self.assertEqual(italic_line.text, "<i>Italic positioned text</i>")
        self.assertEqual(italic_line.metadata.get('override_tags_start'), "{\\pos(100,200)}")
        
        # Verify bold formatting preserved in GUI
        bold_line = lines[1]
        log_input_expected_result("Composite bold in GUI", "<b>Green bold text</b>", bold_line.text)
        self.assertEqual(bold_line.text, "<b>Green bold text</b>")
        self.assertEqual(bold_line.metadata.get('override_tags_start'), "{\\c&H00FF00&}")
        
        # Test round-trip - verify both positioning and formatting restored
        composed = self.handler.compose(data)
        log_input_expected_result("Round-trip composite preservation", True, 
                                "{\\pos(100,200)}{\\i1}Italic positioned text{\\i0}" in composed)
        log_input_expected_result("Round-trip composite bold preservation", True,
                                "{\\c&H00FF00&}{\\b1}Green bold text{\\b0}" in composed)
        
        self.assertIn("{\\pos(100,200)}{\\i1}Italic positioned text{\\i0}", composed)
        self.assertIn("{\\c&H00FF00&}{\\b1}Green bold text{\\b0}", composed)

if __name__ == '__main__':
    unittest.main()
