from PySide6.QtCore import QCoreApplication

from GuiSubtrans.ProjectDataModel import ProjectDataModel
from GuiSubtrans.ViewModel.TestableViewModel import TestableViewModel
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

    def setUp(self) -> None:
        super().setUp()
        self._viewmodels_to_cleanup : list[TestableViewModel] = []

    def tearDown(self) -> None:
        """Clean up Qt viewmodels to prevent crashes"""
        for viewmodel in self._viewmodels_to_cleanup:
            viewmodel.deleteLater()
        if self._viewmodels_to_cleanup:
            QCoreApplication.processEvents()
        self._viewmodels_to_cleanup.clear()
        super().tearDown()

    def create_test_subtitles(self, line_counts : list[list[int]]) -> Subtitles:
        """Build subtitles from line counts."""
        return BuildSubtitlesFromLineCounts(line_counts)

    def create_project_datamodel(self, subtitles : Subtitles|None = None) -> ProjectDataModel:
        """Create a ProjectDataModel for the provided subtitles."""
        project = self.create_subtitle_project(subtitles)
        return ProjectDataModel(project, self.options)

    def create_datamodel_from_line_counts(self, line_counts : list[list[int]]) -> tuple[ProjectDataModel, Subtitles]:
        """Build subtitles from line counts and wrap them in a ProjectDataModel."""
        subtitles = BuildSubtitlesFromLineCounts(line_counts)
        datamodel = self.create_project_datamodel(subtitles)
        return datamodel, subtitles

    def create_testable_viewmodel(self, subtitles : Subtitles) -> TestableViewModel:
        """Create a TestableViewModel for the provided subtitles."""
        viewmodel = TestableViewModel(self)
        viewmodel.CreateModel(subtitles)
        viewmodel.clear_signal_history()  # Clear any signals from initial setup
        self._viewmodels_to_cleanup.append(viewmodel)
        return viewmodel

    def create_testable_viewmodel_from_line_counts(self, line_counts : list[list[int]]) -> TestableViewModel:
        """Helper to create and set up a testable view model from line counts"""
        subtitles = BuildSubtitlesFromLineCounts(line_counts)
        return self.create_testable_viewmodel(subtitles)

