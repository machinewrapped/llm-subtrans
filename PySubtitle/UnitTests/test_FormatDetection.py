import os
import tempfile
import unittest

from PySubtitle.Subtitles import Subtitles
from PySubtitle.Helpers.Tests import log_test_name, log_input_expected_result


class TestFormatDetection(unittest.TestCase):
    def _write_temp(self, content : str) -> str:
        f = tempfile.NamedTemporaryFile(delete=False, suffix='.txt')
        f.write(content.encode('utf-8'))
        f.flush()
        f.close()
        self.addCleanup(os.remove, f.name)
        return f.name

    def test_detect_srt_with_txt_extension(self):
        log_test_name('detect srt with txt extension')
        content = "1\n00:00:01,000 --> 00:00:02,000\nHello\n"
        path = self._write_temp(content)
        subtitles = Subtitles(path)
        try:
            subtitles.LoadSubtitles()
        except Exception as e:
            log_input_expected_result('exception', '.srt', e)
            self.fail(f'LoadSubtitles raised {e}')
        log_input_expected_result('format', '.srt', subtitles.format)
        self.assertEqual('.srt', subtitles.format)

    def test_detect_ass_with_txt_extension(self):
        log_test_name('detect ass with txt extension')
        ass_content = """[Script Info]\nScriptType: v4.00+\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,0,2,0,0,0,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\nDialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,Hello\n"""
        path = self._write_temp(ass_content)
        subtitles = Subtitles(path)
        try:
            subtitles.LoadSubtitles()
        except Exception as e:
            log_input_expected_result('exception', '.ass', e)
            self.fail(f'LoadSubtitles raised {e}')
        log_input_expected_result('format', '.ass', subtitles.format)
        self.assertEqual('.ass', subtitles.format)


if __name__ == '__main__':
    unittest.main()

