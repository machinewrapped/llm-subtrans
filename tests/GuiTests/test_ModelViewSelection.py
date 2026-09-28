from PySide6.QtCore import QCoreApplication, QItemSelectionModel, QModelIndex

from GuiSubtrans.CommandQueue import CommandQueue
from GuiSubtrans.GuiSubtitleTestCase import GuiSubtitleTestCase
from GuiSubtrans.ProjectActions import ProjectActions
from GuiSubtrans.Widgets.ModelView import ModelView


class ModelViewSelectionTests(GuiSubtitleTestCase):
    """Test how tree and subtitle view selections combine into a ProjectSelection."""

    REPLACE = QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows
    EXTEND = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows

    def setUp(self) -> None:
        super().setUp()

        # Scene 1: batch 1 = lines 1-3, batch 2 = lines 4-5. Scene 2: batch 1 = lines 6-7
        viewmodel = self.create_testable_viewmodel_from_line_counts([[3, 2], [2]])
        self.view = ModelView(ProjectActions(CommandQueue(None)))
        self.view.SetViewModel(viewmodel)

    def tearDown(self) -> None:
        self.view.deleteLater()
        QCoreApplication.processEvents()
        super().tearDown()

    def _select_in_tree(self, scene_row : int, batch_row : int|None = None, flags : QItemSelectionModel.SelectionFlag = REPLACE) -> None:
        tree = self.view.scenes_view
        model = tree.model()
        index = model.index(scene_row, 0, QModelIndex())
        if batch_row is not None:
            index = model.index(batch_row, 0, index)

        tree.selectionModel().select(index, flags)
        QCoreApplication.processEvents()

    def _select_subtitle_rows(self, rows : list[int]) -> None:
        subtitle_view = self.view.content_view.subtitle_view
        model = subtitle_view.model()
        selection_model = subtitle_view.selectionModel()
        for row in rows:
            selection_model.select(model.index(row, 0), self.EXTEND)
        QCoreApplication.processEvents()

    def _effective_line_numbers(self) -> list[int]:
        return sorted(line.number for line in self.view.GetSelection().effective_lines)

    def test_selected_lines_are_scoped_within_selected_batch(self) -> None:
        self._select_in_tree(0, 0)
        self._select_subtitle_rows([0, 1])

        self.assertLoggedSequenceEqual("lines picked in batch (1,1)", [1, 2], self._effective_line_numbers())

    def test_selecting_another_scene_clears_selected_lines(self) -> None:
        self._select_in_tree(0, 0)
        self._select_subtitle_rows([0, 1])

        self._select_in_tree(1)

        selection = self.view.GetSelection()
        self.assertLoggedFalse("no lines remain selected", selection.AnyLines())
        self.assertLoggedSequenceEqual("lines of scene 2", [6, 7], self._effective_line_numbers())

    def test_selecting_sibling_batch_clears_selected_lines(self) -> None:
        self._select_in_tree(0, 0)
        self._select_subtitle_rows([0, 1])

        self._select_in_tree(0, 1)

        selection = self.view.GetSelection()
        self.assertLoggedFalse("no lines remain selected", selection.AnyLines())
        self.assertLoggedSequenceEqual("lines of batch (1,2)", [4, 5], self._effective_line_numbers())

    def test_extending_tree_selection_clears_selected_lines(self) -> None:
        self._select_in_tree(0, 0)
        self._select_subtitle_rows([0, 1])

        self._select_in_tree(0, 1, flags=self.EXTEND)

        selection = self.view.GetSelection()
        self.assertLoggedFalse("no lines remain selected", selection.AnyLines())
        self.assertLoggedSequenceEqual("lines of both batches", [1, 2, 3, 4, 5], self._effective_line_numbers())
