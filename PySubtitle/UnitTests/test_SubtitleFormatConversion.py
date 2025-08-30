import os
import tempfile
import unittest
from copy import deepcopy

from PySubtitle.Options import Options
from PySubtitle.SubtitleProject import SubtitleProject
from PySubtitle.Formats.SrtFileHandler import SrtFileHandler
from PySubtitle.Formats.AssFileHandler import AssFileHandler
from PySubtitle.SubtitleSerialisation import SubtitleEncoder

ASS_SAMPLE = """[Script Info]
Title: Sample ASS
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,0,2,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,Hello ASS!
"""

SRT_SAMPLE = """1\n00:00:01,000 --> 00:00:02,000\nHello SRT!\n"""

class TestSubtitleFormatConversion(unittest.TestCase):
    def _write_temp(self, suffix: str, content: str) -> str:
        f = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        self.addCleanup(os.remove, f.name)
        f.write(content.encode("utf-8"))
        f.flush()
        f.close()
        return f.name

    def test_ass_to_srt_conversion(self):
        ass_path = self._write_temp(".ass", ASS_SAMPLE)
        project = SubtitleProject(Options())
        project.InitialiseProject(ass_path)
        self.assertIsInstance(project.subtitles.file_handler, AssFileHandler)
        out_path = ass_path + ".srt"
        project.ConvertFormat('.srt')
        self.assertIsInstance(project.subtitles.file_handler, SrtFileHandler)
        project.SaveOriginal(out_path)
        self.assertTrue(os.path.exists(out_path))

    def test_srt_to_ass_conversion(self):
        srt_path = self._write_temp(".srt", SRT_SAMPLE)
        project = SubtitleProject(Options())
        project.InitialiseProject(srt_path)
        self.assertIsInstance(project.subtitles.file_handler, SrtFileHandler)
        out_path = srt_path + ".ass"
        project.ConvertFormat('.ass')
        self.assertIsInstance(project.subtitles.file_handler, AssFileHandler)
        project.SaveOriginal(out_path)
        self.assertTrue(os.path.exists(out_path))

    def test_project_roundtrip_after_conversion(self):
        srt_path = self._write_temp(".srt", SRT_SAMPLE)
        project = SubtitleProject(Options())
        project.InitialiseProject(srt_path)
        project.ConvertFormat('.ass')
        tmp_project = tempfile.NamedTemporaryFile(delete=False, suffix=".subtrans")
        tmp_project.close()
        project.WriteProjectToFile(tmp_project.name, encoder_class=SubtitleEncoder)

        project2 = SubtitleProject(Options())
        project2.ReadProjectFile(tmp_project.name)
        self.assertIsInstance(project2.subtitles.file_handler, AssFileHandler)
        self.assertEqual(project2.subtitles.settings.get('format'), '.ass')

    def test_translation_data_converted(self):
        srt_path = self._write_temp(".srt", SRT_SAMPLE)
        project = SubtitleProject(Options())
        project.InitialiseProject(srt_path)
        # Set translated lines based on originals
        translated = deepcopy(project.subtitles.originals)
        translated[0].text = "Bonjour SRT!"
        project.subtitles.translated = translated
        project.ConvertFormat('.ass')
        self.assertEqual(project.subtitles.translated[0].text, "Bonjour SRT!")
        self.assertEqual(project.subtitles.metadata.get('format'), 'ass')

if __name__ == '__main__':
    unittest.main()
