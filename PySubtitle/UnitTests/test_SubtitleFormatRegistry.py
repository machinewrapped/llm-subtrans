from collections.abc import Iterator
from typing import TextIO
import unittest

from PySubtitle.SubtitleFileHandler import SubtitleFileHandler
from PySubtitle.SubtitleFormatRegistry import SubtitleFormatRegistry
from PySubtitle.Formats.SrtFileHandler import SrtFileHandler
from PySubtitle.SubtitleLine import SubtitleLine
from PySubtitle.Helpers.Tests import (
    log_input_expected_error,
    log_input_expected_result,
    log_test_name,
    skip_if_debugger_attached,
)


class DummySrtHandler(SubtitleFileHandler):
    def parse_file(self, file_obj : TextIO) -> Iterator[SubtitleLine]:
        return iter([])

    def parse_string(self, content : str) -> Iterator[SubtitleLine]:
        return iter([])

    def compose_lines(self, lines : list[SubtitleLine], reindex : bool = True) -> str:
        return ""

    def get_file_extensions(self) -> list[str]:
        return ['.srt']


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
        SubtitleFormatRegistry.register_handler(DummySrtHandler, priority=1)
        handler = SubtitleFormatRegistry.get_handler_by_extension('.srt')
        log_input_expected_result('priority', DummySrtHandler, handler)
        self.assertIs(handler, DummySrtHandler)

        SubtitleFormatRegistry.register_handler(SrtFileHandler, priority=0)
        handler_after = SubtitleFormatRegistry.get_handler_by_extension('.srt')
        log_input_expected_result('priority', DummySrtHandler, handler_after)
        self.assertIs(handler_after, DummySrtHandler)


if __name__ == '__main__':
    unittest.main()
