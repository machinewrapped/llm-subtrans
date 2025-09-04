import os
import tempfile
import unittest
from typing import TextIO
from unittest.mock import patch, MagicMock

from PySubtitle.SubtitleFileHandler import SubtitleFileHandler
from PySubtitle.SubtitleFormatRegistry import SubtitleFormatRegistry
from PySubtitle.Formats.SrtFileHandler import SrtFileHandler
from PySubtitle.SubtitleData import SubtitleData
from PySubtitle.SubtitleError import SubtitleParseError
from PySubtitle.Helpers.Tests import (
    log_input_expected_error,
    log_input_expected_result,
    log_test_name,
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


class TestSubtitleFormatRegistry(unittest.TestCase):
    def setUp(self):
        SubtitleFormatRegistry.clear()
        SubtitleFormatRegistry.discover()

    def test_AutoDiscovery(self):
        log_test_name("AutoDiscovery")
        handler = SubtitleFormatRegistry.get_handler_by_extension('.srt')
        log_input_expected_result('.srt', SrtFileHandler, handler)
        self.assertIs(handler, SrtFileHandler)

    def test_UnknownExtension(self):
        if skip_if_debugger_attached("UnknownExtension"):
            return

        log_test_name("UnknownExtension")
        with self.assertRaises(ValueError) as e:
            SubtitleFormatRegistry.get_handler_by_extension('.unknown')
        log_input_expected_error('.unknown', ValueError, e.exception)

    def test_EnumerateFormats(self):
        log_test_name("EnumerateFormats")
        formats = SubtitleFormatRegistry.enumerate_formats()
        log_input_expected_result('contains .srt', True, '.srt' in formats)
        self.assertIn('.srt', formats)

    def test_CreateHandler(self):
        log_test_name("CreateHandler")
        handler = SubtitleFormatRegistry.create_handler('.srt')
        log_input_expected_result('.srt', SrtFileHandler, type(handler))
        self.assertIsInstance(handler, SrtFileHandler)

    def test_DuplicateRegistrationPriority(self):
        log_test_name("DuplicateRegistrationPriority")

        SubtitleFormatRegistry.disable_autodiscovery()

        SubtitleFormatRegistry.register_handler(DummySrtHandler)
        handler = SubtitleFormatRegistry.get_handler_by_extension('.srt')
        log_input_expected_result('priority', DummySrtHandler, handler)
        self.assertIs(handler, DummySrtHandler)

        SubtitleFormatRegistry.register_handler(SrtFileHandler)
        handler_after = SubtitleFormatRegistry.get_handler_by_extension('.srt')
        log_input_expected_result('priority', SrtFileHandler, handler_after)
        self.assertIs(handler_after, SrtFileHandler)

        SubtitleFormatRegistry.clear()

    def test_CreateHandlerWithFilename(self):
        log_test_name("CreateHandlerWithFilename")
        handler = SubtitleFormatRegistry.create_handler(filename="test.srt")
        log_input_expected_result("test.srt", SrtFileHandler, type(handler))
        self.assertIsInstance(handler, SrtFileHandler)

    def test_CreateHandlerWithNoExtensionOrFilename(self):
        if skip_if_debugger_attached("CreateHandlerWithNoExtensionOrFilename"):
            return
            
        log_test_name("CreateHandlerWithNoExtensionOrFilename")
        with self.assertRaises(ValueError) as e:
            SubtitleFormatRegistry.create_handler()
        log_input_expected_error("None", ValueError, e.exception)

    def test_CreateHandlerWithEmptyExtension(self):
        if skip_if_debugger_attached("CreateHandlerWithEmptyExtension"):
            return
            
        log_test_name("CreateHandlerWithEmptyExtension")
        with self.assertRaises(ValueError) as e:
            SubtitleFormatRegistry.create_handler(extension="")
        log_input_expected_error('""', ValueError, e.exception)

    def test_CreateHandlerWithInvalidFilename(self):
        if skip_if_debugger_attached("CreateHandlerWithInvalidFilename"):
            return
            
        log_test_name("CreateHandlerWithInvalidFilename")
        with self.assertRaises(ValueError) as e:
            SubtitleFormatRegistry.create_handler(filename="test")
        log_input_expected_error("test", ValueError, e.exception)

    def test_ListAvailableFormats(self):
        log_test_name("ListAvailableFormats")
        formats = SubtitleFormatRegistry.list_available_formats()
        log_input_expected_result("contains .srt", True, ".srt" in formats)
        self.assertIn(".srt", formats)
        self.assertIsInstance(formats, str)

    def test_ListAvailableFormatsEmpty(self):
        log_test_name("ListAvailableFormatsEmpty")
        SubtitleFormatRegistry.disable_autodiscovery()
        formats = SubtitleFormatRegistry.list_available_formats()
        log_input_expected_result("empty registry", "None", formats)
        self.assertEqual("None", formats)
        SubtitleFormatRegistry.discover()

    def test_GetFormatFromFilename(self):
        log_test_name("GetFormatFromFilename")
        
        extension = SubtitleFormatRegistry.get_format_from_filename("test.srt")
        log_input_expected_result("test.srt", ".srt", extension)
        self.assertEqual(".srt", extension)
        
        extension = SubtitleFormatRegistry.get_format_from_filename("test.SRT")
        log_input_expected_result("test.SRT", ".srt", extension)
        self.assertEqual(".srt", extension)
        
        extension = SubtitleFormatRegistry.get_format_from_filename("test")
        log_input_expected_result("test", None, extension)
        self.assertIsNone(extension)
        
        extension = SubtitleFormatRegistry.get_format_from_filename("path/to/file.vtt")
        log_input_expected_result("path/to/file.vtt", ".vtt", extension)
        self.assertEqual(".vtt", extension)

    def test_DetectFormatAndLoadFile(self):
        log_test_name("DetectFormatAndLoadFile")
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.srt', delete=False, encoding='utf-8') as f:
            f.write("1\n00:00:01,000 --> 00:00:02,000\nTest subtitle\n")
            temp_path = f.name
        
        try:
            data = SubtitleFormatRegistry.detect_format_and_load_file(temp_path)
            log_input_expected_result("metadata has detected_format", True, 'detected_format' in data.metadata)
            self.assertIn('detected_format', data.metadata)
            self.assertIsInstance(data, SubtitleData)
        finally:
            os.unlink(temp_path)

    @patch('pysubs2.load')
    def test_DetectFormatAndLoadFileError(self, mock_load):
        if skip_if_debugger_attached("DetectFormatAndLoadFileError"):
            return
            
        log_test_name("DetectFormatAndLoadFileError")
        mock_load.side_effect = Exception("Parse error")
        
        with self.assertRaises(SubtitleParseError) as e:
            SubtitleFormatRegistry.detect_format_and_load_file("nonexistent.srt")
        log_input_expected_error("nonexistent.srt", SubtitleParseError, e.exception)

    @patch('pysubs2.load')
    def test_DetectFormatAndLoadFileUnicodeError(self, mock_load):
        log_test_name("DetectFormatAndLoadFileUnicodeError")
        
        mock_subs = MagicMock()
        mock_subs.format = "srt"
        
        mock_load.side_effect = [UnicodeDecodeError('utf-8', b'', 0, 1, 'invalid'), mock_subs]
        
        with patch.object(SubtitleFormatRegistry, 'create_handler') as mock_create:
            mock_handler = MagicMock()
            mock_handler.load_file.return_value = SubtitleData(lines=[], metadata={})
            mock_create.return_value = mock_handler
            
            data = SubtitleFormatRegistry.detect_format_and_load_file("test.srt")
            log_input_expected_result("fallback encoding used", 2, mock_load.call_count)
            self.assertEqual(2, mock_load.call_count)
            self.assertIsInstance(data, SubtitleData)

    def test_ClearMethod(self):
        log_test_name("ClearMethod")
        
        SubtitleFormatRegistry.discover()
        formats_before = len(SubtitleFormatRegistry.enumerate_formats())
        log_input_expected_result("formats before clear", True, formats_before > 0)
        self.assertGreater(formats_before, 0)
        
        SubtitleFormatRegistry.disable_autodiscovery()
        formats_after = len(SubtitleFormatRegistry.enumerate_formats())
        log_input_expected_result("formats after clear", 0, formats_after)
        self.assertEqual(0, formats_after)
        
        SubtitleFormatRegistry.discover()

    def test_DiscoverMethod(self):
        log_test_name("DiscoverMethod")
        
        SubtitleFormatRegistry.disable_autodiscovery()
        formats_before = len(SubtitleFormatRegistry.enumerate_formats())
        log_input_expected_result("formats before discover", 0, formats_before)
        self.assertEqual(0, formats_before)
        
        SubtitleFormatRegistry.discover()
        formats_after = len(SubtitleFormatRegistry.enumerate_formats())
        log_input_expected_result("formats after discover", True, formats_after > 0)
        self.assertGreater(formats_after, 0)

    def test_EnsureDiscoveredBehavior(self):
        log_test_name("EnsureDiscoveredBehavior")
        
        SubtitleFormatRegistry.disable_autodiscovery()
        formats_before = len(SubtitleFormatRegistry._handlers)
        log_input_expected_result("handlers before access", 0, formats_before)
        self.assertEqual(0, formats_before)
        
        SubtitleFormatRegistry.enable_autodiscovery()
        formats = SubtitleFormatRegistry.enumerate_formats()
        formats_after = len(SubtitleFormatRegistry._handlers)
        log_input_expected_result("handlers after access", True, formats_after > 0)
        self.assertGreater(formats_after, 0)
        
        log_input_expected_result("formats list non-empty", True, len(formats) > 0)
        self.assertGreater(len(formats), 0)
        
        log_input_expected_result("discovered flag", True, SubtitleFormatRegistry._discovered)
        self.assertTrue(SubtitleFormatRegistry._discovered)

    def test_RegisterHandlerWithLowerPriority(self):
        log_test_name("RegisterHandlerWithLowerPriority")
        
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
        log_input_expected_result('before lower priority', SrtFileHandler, handler_before)
        self.assertIs(handler_before, SrtFileHandler)
        
        SubtitleFormatRegistry.register_handler(LowerPrioritySrtHandler)
        handler_after = SubtitleFormatRegistry.get_handler_by_extension('.srt')
        log_input_expected_result('after lower priority', SrtFileHandler, handler_after)
        self.assertIs(handler_after, SrtFileHandler)
        
        SubtitleFormatRegistry.clear()

    def test_CaseInsensitiveExtensions(self):
        log_test_name("CaseInsensitiveExtensions")
        
        handler_lower = SubtitleFormatRegistry.get_handler_by_extension('.srt')
        handler_upper = SubtitleFormatRegistry.get_handler_by_extension('.SRT')
        handler_mixed = SubtitleFormatRegistry.get_handler_by_extension('.Srt')
        
        log_input_expected_result('case insensitive', True, handler_lower == handler_upper == handler_mixed)
        self.assertEqual(handler_lower, handler_upper)
        self.assertEqual(handler_upper, handler_mixed)

    def test_DisableAutodiscovery(self):
        log_test_name("DisableAutodiscovery")
        
        SubtitleFormatRegistry.discover()
        formats_before = len(SubtitleFormatRegistry.enumerate_formats())
        log_input_expected_result("formats before disable", True, formats_before > 0)
        self.assertGreater(formats_before, 0)
        
        SubtitleFormatRegistry.disable_autodiscovery()
        formats_after = len(SubtitleFormatRegistry.enumerate_formats())
        discovered_flag = SubtitleFormatRegistry._discovered
        
        log_input_expected_result("formats after disable", 0, formats_after)
        self.assertEqual(0, formats_after)
        log_input_expected_result("discovered flag after disable", True, discovered_flag)
        self.assertTrue(discovered_flag)
        
        SubtitleFormatRegistry.discover()

    def test_EnableAutodiscovery(self):
        log_test_name("EnableAutodiscovery")
        
        SubtitleFormatRegistry.disable_autodiscovery()
        discovered_flag_before = SubtitleFormatRegistry._discovered
        log_input_expected_result("discovered flag before enable", True, discovered_flag_before)
        self.assertTrue(discovered_flag_before)
        
        SubtitleFormatRegistry.enable_autodiscovery()
        discovered_flag_after = SubtitleFormatRegistry._discovered
        log_input_expected_result("discovered flag after enable", False, discovered_flag_after)
        self.assertFalse(discovered_flag_after)
        
        SubtitleFormatRegistry.discover()

    def test_DoubleDiscoveryBehavior(self):
        log_test_name("DoubleDiscoveryBehavior")
        
        SubtitleFormatRegistry.clear()
        SubtitleFormatRegistry.discover()
        handlers_after_first = dict(SubtitleFormatRegistry._handlers)
        priorities_after_first = dict(SubtitleFormatRegistry._priorities)
        
        SubtitleFormatRegistry.discover()
        handlers_after_second = dict(SubtitleFormatRegistry._handlers)
        priorities_after_second = dict(SubtitleFormatRegistry._priorities)
        
        log_input_expected_result("handlers unchanged after double discovery", handlers_after_first, handlers_after_second)
        self.assertEqual(handlers_after_first, handlers_after_second)
        
        log_input_expected_result("priorities unchanged after double discovery", priorities_after_first, priorities_after_second)
        self.assertEqual(priorities_after_first, priorities_after_second)


if __name__ == '__main__':
    unittest.main()
