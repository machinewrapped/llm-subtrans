import os
import tempfile
from datetime import timedelta

from GuiSubtrans.Commands.SaveTranslationFile import SaveTranslationFile
from GuiSubtrans.ProjectDataModel import ProjectDataModel
from PySubtrans.Formats.SrtFileHandler import SrtFileHandler
from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Options import Options
from PySubtrans.SubtitleBuilder import SubtitleBuilder
from PySubtrans.SubtitleEditor import SubtitleEditor
from PySubtrans.SubtitleProject import SubtitleProject


class SaveTranslationCommandTests(LoggedTestCase):

    def test_SaveTranslationFile_uses_current_project_options(self):
        subtitles = (SubtitleBuilder(max_batch_size=1)
            .AddLines([
                (timedelta(seconds=1), timedelta(seconds=1.1), "abcdefghij"),
            ])
            .Build())
        with SubtitleEditor(subtitles) as editor:
            editor.DuplicateOriginalsAsTranslations()

        project = SubtitleProject()
        project.subtitles = subtitles
        datamodel = ProjectDataModel(project, Options())
        datamodel.UpdateSettings(Options({
            'extend_short_subtitles': True,
            'min_line_duration': 0.8,
            'seconds_per_character': 0.1,
            'min_gap': 0.05,
        }))

        with tempfile.NamedTemporaryFile(delete=False, suffix=".srt") as output_file:
            output_path = output_file.name
        self.addCleanup(os.remove, output_path)

        command = SaveTranslationFile(project, output_path)
        command.SetDataModel(datamodel)
        command.execute()

        output_data = SrtFileHandler().load_file(output_path)
        self.assertLoggedEqual("duration extended from GUI options", timedelta(seconds=2), output_data.lines[0].end)
        self.assertLoggedNotIn("save option not stored in project settings", 'extend_short_subtitles', subtitles.settings)
