from PySide6.QtCore import QCoreApplication

from GuiSubtrans.ProjectDataModel import ProjectDataModel
from PySubtrans.Helpers.TestCases import BuildSubtitlesFromLineCounts, SubtitleTestCase
from PySubtrans.Subtitles import Subtitles


class GuiSubtitleTestCase(SubtitleTestCase):
    """Test case with helpers for GUI-level ProjectDataModel interactions."""
    _qt_app : QCoreApplication|None = None

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        if QCoreApplication.instance() is None:
            cls._qt_app = QCoreApplication([])
        else:
            cls._qt_app = QCoreApplication.instance()

    def create_project_datamodel(self, subtitles : Subtitles|None = None) -> ProjectDataModel:
        """Create a ProjectDataModel for the provided subtitles."""
        project = self.create_subtitle_project(subtitles)
        return ProjectDataModel(project, self.options)

    def create_datamodel_from_line_counts(self, line_counts : list[list[int]]) -> tuple[ProjectDataModel, Subtitles]:
        """Build subtitles from line counts and wrap them in a ProjectDataModel."""
        subtitles = BuildSubtitlesFromLineCounts(line_counts)
        datamodel = self.create_project_datamodel(subtitles)
        return datamodel, subtitles
