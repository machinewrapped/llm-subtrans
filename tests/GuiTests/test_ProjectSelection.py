from PySide6.QtCore import QModelIndex

from GuiSubtrans.GuiSubtitleTestCase import GuiSubtitleTestCase
from GuiSubtrans.ProjectSelection import ProjectSelection, SelectionBatch, SelectionLine, SelectionScene
from GuiSubtrans.ScenesBatchesModel import ScenesBatchesModel
from GuiSubtrans.ViewModel.LineItem import LineItem
from GuiSubtrans.ViewModel.TestableViewModel import TestableViewModel
from GuiSubtrans.ViewModel.ViewModelUpdate import ModelUpdate


class ProjectSelectionTests(GuiSubtitleTestCase):
    """Test resolution of explicit line selections vs batch/scene fallback selections."""

    def test_effective_lines_prefers_explicit_selection_over_implicit_batch_lines(self) -> None:
        selection = ProjectSelection()

        # Simulate selecting a batch in the scenes tree: every line in the batch is
        # added to the selection, but only as an implicit (unselected) member.
        selection.batches[(1, 1)] = SelectionBatch((1, 1), selected=True, translated=True)
        selection.lines[1] = SelectionLine(1, 1, 1, False, translated=True)
        selection.lines[2] = SelectionLine(1, 1, 2, False, translated=False)

        self.assertLoggedSequenceEqual(
            'no explicit line selection uses every implicit line',
            [1, 2],
            sorted(line.number for line in selection.effective_lines),
        )

        # Simulate the user then explicitly selecting only one row in the content view.
        selection.AddSelectedLines([SelectionLine(1, 1, 1, True, translated=True)])

        self.assertLoggedSequenceEqual(
            'explicit line selection overrides implicit batch lines',
            [1],
            sorted(line.number for line in selection.effective_lines),
        )

    def test_all_lines_translated_ignores_untranslated_implicit_lines_when_a_line_is_selected(self) -> None:
        selection = ProjectSelection()
        selection.batches[(1, 1)] = SelectionBatch((1, 1), selected=True, translated=False)
        selection.lines[1] = SelectionLine(1, 1, 1, False, translated=True)
        selection.lines[2] = SelectionLine(1, 1, 2, False, translated=False)

        self.assertLoggedFalse(
            'batch with an untranslated implicit line is not all-translated',
            selection.AllLinesTranslated(),
        )

        selection.AddSelectedLines([SelectionLine(1, 1, 1, True, translated=True)])

        self.assertLoggedTrue(
            'explicitly selecting only the translated line ignores the untranslated implicit line',
            selection.AllLinesTranslated(),
        )

    def test_effective_lines_includes_all_batches_in_an_explicitly_selected_scene(self) -> None:
        selection = ProjectSelection()

        # Selecting the scene itself in the tree also adds its batches with selected=False,
        # so a whole-scene selection must be recognised via the scene flag, not the batches.
        selection.scenes[1] = SelectionScene(1, selected=True)
        selection.batches[(1, 1)] = SelectionBatch((1, 1), selected=False, translated=True)
        selection.lines[1] = SelectionLine(1, 1, 1, False, translated=True)
        selection.batches[(1, 2)] = SelectionBatch((1, 2), selected=False, translated=True)
        selection.lines[2] = SelectionLine(1, 2, 2, False, translated=True)

        self.assertLoggedSequenceEqual(
            'every line in the selected scene is included',
            [1, 2],
            sorted(line.number for line in selection.effective_lines),
        )

    def _create_scenes_model(self, line_counts : list[list[int]]) -> ScenesBatchesModel:
        """Create the scenes/batches tree model used by the project view."""
        viewmodel = self.create_testable_viewmodel_from_line_counts(line_counts)
        return ScenesBatchesModel(viewmodel)

    def _scene_index(self, model : ScenesBatchesModel, scene_row : int) -> QModelIndex:
        return model.index(scene_row, 0, QModelIndex())

    def _batch_index(self, model : ScenesBatchesModel, scene_row : int, batch_row : int) -> QModelIndex:
        return model.index(batch_row, 0, self._scene_index(model, scene_row))

    def test_append_batch_does_not_include_sibling_batches(self) -> None:
        # Scene 1 has batches of lines 1-3 and 4-5, scene 2 has lines 6-7
        model = self._create_scenes_model([[3, 2], [2]])

        selection = ProjectSelection()
        selection.AppendItem(model, self._batch_index(model, 0, 0))

        self.assertLoggedSequenceEqual("registered scenes", [1], selection.scene_numbers)
        self.assertLoggedEqual("parent scene is not selected", 0, len(selection.selected_scenes))
        self.assertLoggedSequenceEqual("registered batches", [(1, 1)], selection.batch_numbers)
        self.assertLoggedSequenceEqual("lines in selection", [1, 2, 3], selection.line_numbers)
        self.assertLoggedSequenceEqual(
            "effective lines",
            [1, 2, 3],
            sorted(line.number for line in selection.effective_lines),
        )

    def test_append_scene_includes_all_its_batches(self) -> None:
        model = self._create_scenes_model([[3, 2], [2]])

        selection = ProjectSelection()
        selection.AppendItem(model, self._scene_index(model, 0))

        self.assertLoggedEqual("scene is selected", 1, len(selection.selected_scenes))
        self.assertLoggedSequenceEqual("registered batches", [(1, 1), (1, 2)], selection.batch_numbers)
        self.assertLoggedEqual("batches are implicit members", 0, len(selection.selected_batches))
        self.assertLoggedSequenceEqual(
            "effective lines",
            [1, 2, 3, 4, 5],
            sorted(line.number for line in selection.effective_lines),
        )

    def test_append_batches_from_different_scenes(self) -> None:
        model = self._create_scenes_model([[3, 2], [2, 2]])

        selection = ProjectSelection()
        selection.AppendItem(model, self._batch_index(model, 0, 1))
        selection.AppendItem(model, self._batch_index(model, 1, 0))

        self.assertLoggedSequenceEqual("registered scenes", [1, 2], selection.scene_numbers)
        self.assertLoggedSequenceEqual("registered batches", [(1, 2), (2, 1)], selection.batch_numbers)
        self.assertLoggedSequenceEqual(
            "effective lines",
            [4, 5, 6, 7],
            sorted(line.number for line in selection.effective_lines),
        )

    def test_selected_lines_do_not_replace_selected_parent_scene(self) -> None:
        model = self._create_scenes_model([[3, 2]])

        selection = ProjectSelection()
        selection.AppendItem(model, self._scene_index(model, 0))
        selection.AddSelectedLines([SelectionLine(1, 1, 2, True, translated=False)])

        self.assertLoggedEqual("scene remains selected", 1, len(selection.selected_scenes))
        self.assertLoggedSequenceEqual(
            "explicit line selection takes precedence",
            [2],
            [line.number for line in selection.effective_lines],
        )

    def _line_items(self, viewmodel : TestableViewModel, line_numbers : list[int]) -> list[LineItem]:
        line_items = [ viewmodel.GetLineItem(number) for number in line_numbers ]
        return [ item for item in line_items if item is not None ]

    def test_first_line_in_batch_detected_without_tree_selection(self) -> None:
        # Nothing selected in the scenes tree, so the subtitle view shows every line
        viewmodel = self.create_testable_viewmodel_from_line_counts([[3, 2]])

        middle_line = ProjectSelection()
        middle_line.AddLineItems(self._line_items(viewmodel, [2]))
        self.assertLoggedFalse("middle line is not first in batch", middle_line.IsFirstInBatchSelected())

        first_of_second_batch = ProjectSelection()
        first_of_second_batch.AddLineItems(self._line_items(viewmodel, [4]))
        self.assertLoggedTrue("first line of second batch", first_of_second_batch.IsFirstInBatchSelected())

    def test_first_line_in_batch_detected_with_batch_selected(self) -> None:
        viewmodel = self.create_testable_viewmodel_from_line_counts([[3, 2]])
        model = ScenesBatchesModel(viewmodel)

        selection = ProjectSelection()
        selection.AppendItem(model, self._batch_index(model, 0, 1))
        selection.AddLineItems(self._line_items(viewmodel, [5]))
        self.assertLoggedFalse("last line is not first in batch", selection.IsFirstInBatchSelected())

        selection = ProjectSelection()
        selection.AppendItem(model, self._batch_index(model, 0, 1))
        selection.AddLineItems(self._line_items(viewmodel, [4]))
        self.assertLoggedTrue("first line of selected batch", selection.IsFirstInBatchSelected())

    def test_first_line_in_batch_follows_line_removal(self) -> None:
        viewmodel = self.create_testable_viewmodel_from_line_counts([[3]])

        # Resolve the batch bounds before removing the first line
        selection = ProjectSelection()
        selection.AddLineItems(self._line_items(viewmodel, [1]))
        self.assertLoggedTrue("line 1 starts the batch", selection.IsFirstInBatchSelected())

        update = ModelUpdate()
        update.lines.remove((1, 1, 1))
        update.ApplyToViewModel(viewmodel)

        selection = ProjectSelection()
        selection.AddLineItems(self._line_items(viewmodel, [2]))
        self.assertLoggedTrue("line 2 starts the batch after line 1 is removed", selection.IsFirstInBatchSelected())

    def test_all_lines_in_same_batch_distinguishes_scenes(self) -> None:
        viewmodel = self.create_testable_viewmodel_from_line_counts([[2], [2]])

        # Lines 2 and 3 are both in batch 1, but of different scenes
        selection = ProjectSelection()
        selection.AddLineItems(self._line_items(viewmodel, [2, 3]))
        self.assertLoggedFalse("lines in different scenes", selection.AllLinesInSameBatch())

        selection = ProjectSelection()
        selection.AddLineItems(self._line_items(viewmodel, [3, 4]))
        self.assertLoggedTrue("lines in the same batch", selection.AllLinesInSameBatch())

    def test_effective_batch_numbers_combines_scenes_and_batches(self) -> None:
        model = self._create_scenes_model([[3, 2], [2, 2]])

        selection = ProjectSelection()
        selection.AppendItem(model, self._scene_index(model, 0))
        selection.AppendItem(model, self._batch_index(model, 1, 1))

        self.assertLoggedSequenceEqual(
            "batches of the selected scene plus the selected batch",
            [(1, 1), (1, 2), (2, 2)],
            selection.effective_batch_numbers,
        )

    def test_str_describes_each_kind_of_selection(self) -> None:
        # Scene 1: batch 1 = lines 1-3, batch 2 = lines 4-5. Scene 2: batch 1 = lines 6-7
        viewmodel = self.create_testable_viewmodel_from_line_counts([[3, 2], [2]])
        model = ScenesBatchesModel(viewmodel)

        cases : list[tuple[str, list[tuple[int, int|None]], list[int], str]] = [
            ("nothing", [], [], "Nothing selected"),
            ("one batch", [(0, 0)], [], "1 batch with 3 lines"),
            ("batches in different scenes", [(0, 0), (1, 0)], [], "2 batches with 5 lines"),
            ("one scene", [(0, None)], [], "1 scene with 5 lines in 2 batches"),
            ("two scenes", [(0, None), (1, None)], [], "2 scenes with 7 lines in 3 batches"),
            ("scene and batch from another scene", [(0, None), (1, 0)], [], "1 scene and 1 batch with 7 lines"),
            ("one line", [], [2], "1 line selected in 1 batch"),
            ("lines across batches", [], [3, 4], "2 lines selected in 2 batches"),
            ("line within a selected batch", [(0, 0)], [1], "1 line selected in 1 batch"),
            ("lines within a selected scene", [(0, None)], [1, 4], "2 lines selected in 2 batches"),
        ]

        for description, tree_items, line_numbers, expected in cases:
            selection = ProjectSelection()
            for scene_row, batch_row in tree_items:
                index = self._scene_index(model, scene_row) if batch_row is None else self._batch_index(model, scene_row, batch_row)
                selection.AppendItem(model, index)

            selection.AddLineItems(self._line_items(viewmodel, line_numbers))

            self.assertLoggedEqual(description, expected, str(selection))
