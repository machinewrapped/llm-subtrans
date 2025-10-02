import unittest
from datetime import timedelta
from typing import cast

from PySide6.QtCore import QCoreApplication, QModelIndex

from GuiSubtrans.ViewModel.BatchItem import BatchItem
from GuiSubtrans.ViewModel.LineItem import LineItem
from GuiSubtrans.ViewModel.SceneItem import SceneItem
from GuiSubtrans.ViewModel.ViewModel import ProjectViewModel
from GuiSubtrans.ViewModel.ViewModelUpdate import ModelUpdate
from PySubtrans.Helpers.TestCases import BuildSubtitlesFromLineCounts, SubtitleTestCase
from PySubtrans.Helpers.Tests import log_input_expected_result
from PySubtrans.SubtitleBatch import SubtitleBatch
from PySubtrans.SubtitleLine import SubtitleLine
from PySubtrans.SubtitleScene import SubtitleScene
from PySubtrans.Subtitles import Subtitles


class TestableProjectViewModel(ProjectViewModel):
    """
    Subclass of ProjectViewModel that tracks signals for testing.
    """
    def __init__(self):
        super().__init__()
        self.signal_history : list[dict] = []

        # Connect to all relevant signals
        self.dataChanged.connect(self._track_data_changed)
        self.layoutChanged.connect(self._track_layout_changed)
        self.modelReset.connect(self._track_model_reset)

    def _track_data_changed(self, topLeft : QModelIndex, bottomRight : QModelIndex, roles : list[int]) -> None:
        """Track dataChanged signals"""
        self.signal_history.append({
            'signal': 'dataChanged',
            'topLeft': topLeft,
            'bottomRight': bottomRight,
            'roles': roles
        })

    def _track_layout_changed(self) -> None:
        """Track layoutChanged signals"""
        self.signal_history.append({'signal': 'layoutChanged'})

    def _track_model_reset(self) -> None:
        """Track modelReset signals"""
        self.signal_history.append({'signal': 'modelReset'})

    def clear_signal_history(self) -> None:
        """Clear signal history between test operations"""
        self.signal_history.clear()

    def assert_signal_emitted(self, test_case : SubtitleTestCase, signal_name : str, expected_count : int|None = None) -> list[dict]:
        """
        Assert that a specific signal was emitted.
        Returns the list of matching signals for further inspection.

        Args:
            test_case: The test case instance for assertions
            signal_name: Name of the signal ('dataChanged', 'layoutChanged', 'modelReset')
            expected_count: Expected number of times signal was emitted (None = at least once)
        """
        matching_signals = [s for s in self.signal_history if s['signal'] == signal_name]

        if expected_count is None:
            log_input_expected_result(f"{signal_name} emitted", True, len(matching_signals) > 0)
            test_case.assertGreater(len(matching_signals), 0, f"Expected {signal_name} to be emitted")
        else:
            log_input_expected_result(f"{signal_name} count", expected_count, len(matching_signals))
            test_case.assertEqual(len(matching_signals), expected_count,
                                f"Expected {signal_name} to be emitted {expected_count} times, got {len(matching_signals)}")

        return matching_signals

    def assert_no_signal_emitted(self, test_case : SubtitleTestCase, signal_name : str) -> None:
        """
        Assert that a specific signal was NOT emitted.

        Args:
            test_case: The test case instance for assertions
            signal_name: Name of the signal ('dataChanged', 'layoutChanged', 'modelReset')
        """
        matching_signals = [s for s in self.signal_history if s['signal'] == signal_name]
        log_input_expected_result(f"{signal_name} not emitted", 0, len(matching_signals))
        test_case.assertEqual(len(matching_signals), 0,
                            f"Expected {signal_name} to NOT be emitted, but it was emitted {len(matching_signals)} times")


class ProjectViewModelTests(SubtitleTestCase):
    _qt_app : QCoreApplication|None = None

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        if QCoreApplication.instance() is None:
            cls._qt_app = QCoreApplication([])
        else:
            cls._qt_app = QCoreApplication.instance()

    def _create_viewmodel_with_counts(self, line_counts : list[list[int]]) -> tuple[TestableProjectViewModel, Subtitles]:
        subtitles = BuildSubtitlesFromLineCounts(line_counts)

        viewmodel = TestableProjectViewModel()
        viewmodel.CreateModel(subtitles)

        return viewmodel, subtitles

    def _get_scene_item(self, viewmodel : ProjectViewModel, scene_number : int) -> SceneItem:
        """
        Helper to retrieve a scene item from the view model by scene number.
        Scene numbers are stable identifiers, not row positions.
        """
        scene_item = viewmodel.model.get(scene_number)

        log_input_expected_result(f"scene {scene_number} exists", True, scene_item is not None)
        self.assertIsNotNone(scene_item)

        log_input_expected_result(f"scene {scene_number} type", SceneItem, type(scene_item))
        self.assertEqual(type(scene_item), SceneItem)

        return cast(SceneItem, scene_item)

    def _get_batch_item(self, scene_item : SceneItem, scene_number : int, batch_number : int) -> BatchItem:
        """
        Helper to retrieve a batch item from a scene item.
        Returns the BatchItem or None if not found or wrong type.
        """
        batch_item_qt = scene_item.child(batch_number - 1, 0)

        log_input_expected_result(f"batch ({scene_number},{batch_number}) exists", True, batch_item_qt is not None)
        self.assertIsNotNone(batch_item_qt)

        log_input_expected_result(f"batch ({scene_number},{batch_number}) type", BatchItem, type(batch_item_qt))
        self.assertEqual(type(batch_item_qt), BatchItem)

        return cast(BatchItem, batch_item_qt)

    def _get_line_item(self, batch_item : BatchItem, scene_number : int, batch_number : int, line_number : int) -> LineItem:
        """
        Helper to retrieve a line item from a batch item.
        Returns the LineItem or None if not found or wrong type.
        """
        line_item_qt = batch_item.child(line_number - 1, 0)

        log_input_expected_result(f"line ({scene_number},{batch_number},{line_number}) exists", True, line_item_qt is not None)
        self.assertIsNotNone(line_item_qt)

        log_input_expected_result(f"line ({scene_number},{batch_number},{line_number}) type", LineItem, type(line_item_qt))
        self.assertEqual(type(line_item_qt), LineItem)

        return cast(LineItem, line_item_qt)

    def _get_line_numbers_in_batch(self, batch_item : BatchItem) -> list[int]:
        """
        Helper to retrieve all global line numbers from a batch.
        Returns a list of line numbers.
        """
        line_numbers = []
        for i in range(batch_item.line_count):
            line_item = batch_item.child(i, 0)
            if isinstance(line_item, LineItem):
                line_numbers.append(line_item.number)
        return line_numbers

    def _create_batch(self, scene_number : int, batch_number : int, line_count : int, start_line_number : int, start_time : timedelta) -> SubtitleBatch:
        """
        Helper to create a SubtitleBatch with the specified number of lines.
        """
        lines = [
            SubtitleLine.Construct(
                start_line_number + i,
                start_time + timedelta(seconds=i*2),
                start_time + timedelta(seconds=i*2 + 1),
                f"Scene {scene_number} Batch {batch_number} Line {start_line_number + i}",
                {}
            )
            for i in range(line_count)
        ]

        return SubtitleBatch({
            'scene': scene_number,
            'number': batch_number,
            'summary': f"Scene {scene_number} Batch {batch_number}",
            'originals': lines
        })

    def _create_scene(self, scene_number : int, batch_line_counts : list[int], start_line_number : int, start_time : timedelta) -> SubtitleScene:
        """
        Helper to create a SubtitleScene with batches containing the specified line counts.
        """
        batches = []
        line_number = start_line_number
        current_time = start_time

        for batch_index, line_count in enumerate(batch_line_counts, start=1):
            batch = self._create_batch(scene_number, batch_index, line_count, line_number, current_time)
            batches.append(batch)
            line_number += line_count
            current_time += timedelta(seconds=line_count * 2)

        return SubtitleScene({
            'number': scene_number,
            'context': {'summary': f"Scene {scene_number}"},
            'batches': batches
        })

    def test_create_model_from_helper_subtitles(self):
        line_counts = [[3, 2], [1, 1, 2]]
        subtitles = BuildSubtitlesFromLineCounts(line_counts)

        viewmodel = ProjectViewModel()
        viewmodel.CreateModel(subtitles)

        root_item = viewmodel.getRootItem()
        scene_count = root_item.rowCount()
        log_input_expected_result("scene count", len(line_counts), scene_count)
        self.assertEqual(scene_count, len(line_counts))

        for scene_index, expected_batches in enumerate(line_counts, start=1):
            scene_item_qt = root_item.child(scene_index - 1, 0)
            self.assertIsNotNone(scene_item_qt)
            if scene_item_qt is None:
                continue

            log_input_expected_result(f"scene {scene_index} type", SceneItem, type(scene_item_qt))
            self.assertEqual(type(scene_item_qt), SceneItem)

            scene_item: SceneItem = cast(SceneItem, scene_item_qt)
            expected_summary = f"Scene {scene_index}"
            log_input_expected_result(f"scene {scene_index} summary", expected_summary, scene_item.summary)
            self.assertEqual(scene_item.summary, expected_summary)

            log_input_expected_result(f"scene {scene_index} batch count", len(expected_batches), scene_item.batch_count)
            self.assertEqual(scene_item.batch_count, len(expected_batches))

            for batch_index, expected_line_count in enumerate(expected_batches, start=1):
                batch_item_qt = scene_item.child(batch_index - 1, 0)
                self.assertIsNotNone(batch_item_qt)
                if batch_item_qt is None:
                    continue

                log_input_expected_result(
                    f"batch ({scene_index},{batch_index}) type",
                    BatchItem,
                    type(batch_item_qt)
                )
                self.assertEqual(type(batch_item_qt), BatchItem)

                batch_item: BatchItem = cast(BatchItem, batch_item_qt)
                expected_batch_summary = f"Scene {scene_index} Batch {batch_index}"
                log_input_expected_result(
                    f"batch ({scene_index},{batch_index}) summary",
                    expected_batch_summary,
                    batch_item.summary
                )
                self.assertEqual(batch_item.summary, expected_batch_summary)

                log_input_expected_result(
                    f"batch ({scene_index},{batch_index}) line count",
                    expected_line_count,
                    batch_item.line_count
                )
                self.assertEqual(batch_item.line_count, expected_line_count)

                for line_row in range(expected_line_count):
                    line_item_qt = batch_item.child(line_row, 0)
                    self.assertIsNotNone(line_item_qt)
                    if line_item_qt is None:
                        continue

                    log_input_expected_result(
                        f"line ({scene_index},{batch_index},{line_row + 1}) type",
                        LineItem,
                        type(line_item_qt)
                    )
                    self.assertEqual(type(line_item_qt), LineItem)

                    line_item: LineItem = cast(LineItem, line_item_qt)
                    expected_text = f"Scene {scene_index} Batch {batch_index} Line {line_row + 1}"
                    log_input_expected_result(
                        f"line ({scene_index},{batch_index},{line_row + 1}) text",
                        expected_text,
                        line_item.line_text
                    )
                    self.assertEqual(line_item.line_text, expected_text)

    def test_update_scene_summary(self):
        base_counts = [[2, 2], [1, 1]]
        viewmodel, _ = self._create_viewmodel_with_counts(base_counts)
        viewmodel.clear_signal_history()

        update = ModelUpdate()
        update.scenes.update(1, {'summary': 'Scene 1 (edited)'})
        update.ApplyToViewModel(viewmodel)

        scene_one_item = self._get_scene_item(viewmodel, 1)

        log_input_expected_result("scene 1 summary", 'Scene 1 (edited)', scene_one_item.summary)
        self.assertEqual(scene_one_item.summary, 'Scene 1 (edited)')

        # Verify dataChanged was emitted for in-place update
        viewmodel.assert_signal_emitted(self, 'dataChanged', expected_count=1)

    def test_update_batch_summary(self):
        base_counts = [[2, 2], [1, 1]]
        viewmodel, _ = self._create_viewmodel_with_counts(base_counts)
        viewmodel.clear_signal_history()

        update = ModelUpdate()
        update.batches.update((1, 1), {'summary': 'Scene 1 Batch 1 (edited)'})
        update.ApplyToViewModel(viewmodel)

        scene_one_item = self._get_scene_item(viewmodel, 1)
        batch_one_item = self._get_batch_item(scene_one_item, 1, 1)

        log_input_expected_result("batch (1,1) summary", 'Scene 1 Batch 1 (edited)', batch_one_item.summary)
        self.assertEqual(batch_one_item.summary, 'Scene 1 Batch 1 (edited)')

        # Verify dataChanged was emitted (batch setData + scene.emitDataChanged + batch.emitDataChanged = 3)
        # TODO: this count seems high, invesigate whether the explicit calls are needed
        viewmodel.assert_signal_emitted(self, 'dataChanged', expected_count=3)

    def test_update_line_text(self):
        base_counts = [[2, 2], [1, 1]]
        viewmodel, _ = self._create_viewmodel_with_counts(base_counts)
        viewmodel.clear_signal_history()

        update = ModelUpdate()
        update.lines.update((1, 1, 1), {'text': 'Scene 1 Batch 1 Line 1 (edited)'})
        update.ApplyToViewModel(viewmodel)

        scene_one_item = self._get_scene_item(viewmodel, 1)
        batch_one_item = self._get_batch_item(scene_one_item, 1, 1)
        updated_line_item = self._get_line_item(batch_one_item, 1, 1, 1)

        log_input_expected_result(
            "line (1,1,1) text",
            'Scene 1 Batch 1 Line 1 (edited)',
            updated_line_item.line_text
        )
        self.assertEqual(updated_line_item.line_text, 'Scene 1 Batch 1 Line 1 (edited)')

        # Verify dataChanged was emitted (line item update + batch.emitDataChanged = 2)
        # TODO: this count seems high, invesigate whether the explicit calls are needed
        viewmodel.assert_signal_emitted(self, 'dataChanged', expected_count=2)

    def test_add_new_line(self):
        base_counts = [[2, 2], [1, 1]]
        viewmodel, subtitles = self._create_viewmodel_with_counts(base_counts)
        viewmodel.clear_signal_history()

        next_line_number = max(line.number for line in subtitles.originals or []) + 1
        new_line = SubtitleLine.Construct(
            next_line_number,
            timedelta(seconds=90),
            timedelta(seconds=91),
            'Scene 1 Batch 1 Line New',
            {}
        )

        update = ModelUpdate()
        update.lines.add((1, 1, new_line.number), new_line)
        update.ApplyToViewModel(viewmodel)

        scene_one_item = self._get_scene_item(viewmodel, 1)
        batch_one_item = self._get_batch_item(scene_one_item, 1, 1)

        log_input_expected_result("batch (1,1) line count", 3, batch_one_item.line_count)
        self.assertEqual(batch_one_item.line_count, 3)

        new_line_index = batch_one_item.line_count - 1
        new_line_item_qt = batch_one_item.child(new_line_index, 0)
        log_input_expected_result("new line exists", True, new_line_item_qt is not None)
        self.assertIsNotNone(new_line_item_qt)

        log_input_expected_result("new line type", LineItem, type(new_line_item_qt))
        self.assertEqual(type(new_line_item_qt), LineItem)
        new_line_item : LineItem = cast(LineItem, new_line_item_qt)

        log_input_expected_result("new line text", 'Scene 1 Batch 1 Line New', new_line_item.line_text)
        self.assertEqual(new_line_item.line_text, 'Scene 1 Batch 1 Line New')

        # Verify modelReset was emitted for structural change (adding a line)
        viewmodel.assert_signal_emitted(self, 'modelReset', expected_count=1)

    def test_remove_line(self):
        base_counts = [[2, 2], [1, 1]]
        viewmodel, _ = self._create_viewmodel_with_counts(base_counts)
        viewmodel.clear_signal_history()

        update = ModelUpdate()
        update.lines.remove((1, 1, 2))
        update.ApplyToViewModel(viewmodel)

        scene_one_item = self._get_scene_item(viewmodel, 1)
        batch_one_item = self._get_batch_item(scene_one_item, 1, 1)

        log_input_expected_result("batch (1,1) line count", 1, batch_one_item.line_count)
        self.assertEqual(batch_one_item.line_count, 1)

        # Verify modelReset was emitted for structural change (removing a line)
        viewmodel.assert_signal_emitted(self, 'modelReset', expected_count=1)

    def test_add_new_batch(self):
        base_counts = [[2, 2], [1, 1]]
        viewmodel, subtitles = self._create_viewmodel_with_counts(base_counts)
        viewmodel.clear_signal_history()

        next_line_number = max(line.number for line in subtitles.originals or []) + 1
        new_batch_number = len(subtitles.GetScene(1).batches) + 1

        new_batch = self._create_batch(1, new_batch_number, 2, next_line_number, timedelta(seconds=120))

        update = ModelUpdate()
        update.batches.add((1, new_batch.number), new_batch)
        update.ApplyToViewModel(viewmodel)

        scene_one_item = self._get_scene_item(viewmodel, 1)

        expected_batch_count = len(base_counts[0]) + 1
        log_input_expected_result("scene 1 batch count", expected_batch_count, scene_one_item.batch_count)
        self.assertEqual(scene_one_item.batch_count, expected_batch_count)

        new_batch_index = scene_one_item.batch_count - 1
        new_batch_item_qt = scene_one_item.child(new_batch_index, 0)
        log_input_expected_result("new batch exists", True, new_batch_item_qt is not None)
        self.assertIsNotNone(new_batch_item_qt)

        log_input_expected_result("new batch type", BatchItem, type(new_batch_item_qt))
        self.assertEqual(type(new_batch_item_qt), BatchItem)
        new_batch_item : BatchItem = cast(BatchItem, new_batch_item_qt)

        log_input_expected_result("new batch summary", new_batch.summary, new_batch_item.summary)
        self.assertEqual(new_batch_item.summary, new_batch.summary)

        # Verify modelReset was emitted for structural change (adding a batch)
        viewmodel.assert_signal_emitted(self, 'modelReset', expected_count=1)

    def test_remove_batch(self):
        base_counts = [[2, 2], [1, 1]]
        viewmodel, _ = self._create_viewmodel_with_counts(base_counts)
        viewmodel.clear_signal_history()

        update = ModelUpdate()
        update.batches.remove((2, 2))
        update.ApplyToViewModel(viewmodel)

        scene_two_item = self._get_scene_item(viewmodel, 2)

        expected_batch_count = len(base_counts[1]) - 1
        log_input_expected_result("scene 2 batch count", expected_batch_count, scene_two_item.batch_count)
        self.assertEqual(scene_two_item.batch_count, expected_batch_count)

        # Verify modelReset was emitted for structural change (removing a batch)
        viewmodel.assert_signal_emitted(self, 'modelReset', expected_count=1)

    def test_add_new_scene(self):
        base_counts = [[2, 2], [1, 1]]
        viewmodel, subtitles = self._create_viewmodel_with_counts(base_counts)

        initial_scene_count = viewmodel.rowCount()
        log_input_expected_result("initial scene count", len(base_counts), initial_scene_count)
        self.assertEqual(initial_scene_count, len(base_counts))

        viewmodel.clear_signal_history()

        next_line_number = max(line.number for line in subtitles.originals or []) + 1
        new_scene_number = initial_scene_count + 1

        new_scene = self._create_scene(new_scene_number, [1, 1], next_line_number, timedelta(seconds=180))

        update = ModelUpdate()
        update.scenes.add(new_scene.number, new_scene)
        update.ApplyToViewModel(viewmodel)

        root_item = viewmodel.getRootItem()
        final_scene_count = root_item.rowCount()
        log_input_expected_result("final scene count", initial_scene_count + 1, final_scene_count)
        self.assertEqual(final_scene_count, initial_scene_count + 1)

        scene_three_item = self._get_scene_item(viewmodel, 3)

        log_input_expected_result("scene 3 number", 3, scene_three_item.number)
        self.assertEqual(scene_three_item.number, 3)

        log_input_expected_result("scene 3 batch count", 2, scene_three_item.batch_count)
        self.assertEqual(scene_three_item.batch_count, 2)

        # Verify modelReset was emitted for structural change (adding a scene)
        viewmodel.assert_signal_emitted(self, 'modelReset', expected_count=1)

    
    def test_remove_scene(self):
        """Test removing a scene validates remaining scenes are correct"""
        base_counts = [[2, 2], [1, 1, 2], [3]]
        viewmodel, _ = self._create_viewmodel_with_counts(base_counts)
        viewmodel.clear_signal_history()

        # Remove scene 2 (which has 3 batches)
        update = ModelUpdate()
        update.scenes.remove(2)
        update.ApplyToViewModel(viewmodel)

        root_item = viewmodel.getRootItem()
        final_scene_count = root_item.rowCount()
        log_input_expected_result("final scene count", len(base_counts) - 1, final_scene_count)
        self.assertEqual(final_scene_count, len(base_counts) - 1)

        # Verify scene 1 is still intact with correct structure
        scene_one_item = self._get_scene_item(viewmodel, 1)
        log_input_expected_result("scene 1 summary", "Scene 1", scene_one_item.summary)
        self.assertEqual(scene_one_item.summary, "Scene 1")
        log_input_expected_result("scene 1 batch count", 2, scene_one_item.batch_count)
        self.assertEqual(scene_one_item.batch_count, 2)

        # Check scene 1 batches have correct line counts
        batch_1_1 = self._get_batch_item(scene_one_item, 1, 1)
        log_input_expected_result("batch (1,1) line count", 2, batch_1_1.line_count)
        self.assertEqual(batch_1_1.line_count, 2)

        batch_1_2 = self._get_batch_item(scene_one_item, 1, 2)
        log_input_expected_result("batch (1,2) line count", 2, batch_1_2.line_count)
        self.assertEqual(batch_1_2.line_count, 2)

        # Verify scene 3 retains its original number (scene numbers are stable identifiers)
        # After removing scene 2, we should have 2 scenes total: scene 1 and scene 3
        scene_three_item = self._get_scene_item(viewmodel, 3)
        log_input_expected_result("scene 3 summary", "Scene 3", scene_three_item.summary)
        self.assertEqual(scene_three_item.summary, "Scene 3")
        log_input_expected_result("scene 3 batch count", 1, scene_three_item.batch_count)
        self.assertEqual(scene_three_item.batch_count, 1)

        batch_3_1 = self._get_batch_item(scene_three_item, 3, 1)
        log_input_expected_result("batch (3,1) line count", 3, batch_3_1.line_count)
        self.assertEqual(batch_3_1.line_count, 3)

        # Verify modelReset was emitted for structural change
        viewmodel.assert_signal_emitted(self, 'modelReset', expected_count=1)

    
    def test_replace_scene(self):
        """Test replacing a scene validates new structure and unaffected scenes"""
        base_counts = [[2, 2], [1, 1]]
        viewmodel, _ = self._create_viewmodel_with_counts(base_counts)
        viewmodel.clear_signal_history()

        # Create a new scene with different structure - was [2,2], now [3,1]
        replacement_scene = self._create_scene(1, [3, 1], 1, timedelta(seconds=0))

        update = ModelUpdate()
        update.scenes.replace(1, replacement_scene)
        update.ApplyToViewModel(viewmodel)

        # Verify total scene count unchanged
        root_item = viewmodel.getRootItem()
        log_input_expected_result("total scene count", 2, root_item.rowCount())
        self.assertEqual(root_item.rowCount(), 2)

        # Verify replaced scene has new structure
        scene_one_item = self._get_scene_item(viewmodel, 1)
        log_input_expected_result("scene 1 batch count", 2, scene_one_item.batch_count)
        self.assertEqual(scene_one_item.batch_count, 2)

        # Check the first batch has 3 lines (changed from 2)
        batch_one_item = self._get_batch_item(scene_one_item, 1, 1)
        log_input_expected_result("batch (1,1) line count", 3, batch_one_item.line_count)
        self.assertEqual(batch_one_item.line_count, 3)

        # Check the second batch has 1 line (changed from 2)
        batch_two_item = self._get_batch_item(scene_one_item, 1, 2)
        log_input_expected_result("batch (1,2) line count", 1, batch_two_item.line_count)
        self.assertEqual(batch_two_item.line_count, 1)

        # Verify scene 2 is unaffected
        scene_two_item = self._get_scene_item(viewmodel, 2)
        log_input_expected_result("scene 2 batch count", 2, scene_two_item.batch_count)
        self.assertEqual(scene_two_item.batch_count, 2)

        batch_2_1 = self._get_batch_item(scene_two_item, 2, 1)
        log_input_expected_result("batch (2,1) line count", 1, batch_2_1.line_count)
        self.assertEqual(batch_2_1.line_count, 1)

        batch_2_2 = self._get_batch_item(scene_two_item, 2, 2)
        log_input_expected_result("batch (2,2) line count", 1, batch_2_2.line_count)
        self.assertEqual(batch_2_2.line_count, 1)

    
    def test_replace_batch(self):
        """Test replacing a batch validates new lines and unaffected batches"""
        base_counts = [[2, 2, 3], [1, 1]]
        viewmodel, _ = self._create_viewmodel_with_counts(base_counts)
        viewmodel.clear_signal_history()

        # Replace batch (1,2) - was 2 lines, now 5 lines
        replacement_batch = self._create_batch(1, 2, 5, 3, timedelta(seconds=10))

        update = ModelUpdate()
        update.batches.replace((1, 2), replacement_batch)
        update.ApplyToViewModel(viewmodel)

        scene_one_item = self._get_scene_item(viewmodel, 1)

        # Verify scene still has same number of batches
        log_input_expected_result("scene 1 batch count", 3, scene_one_item.batch_count)
        self.assertEqual(scene_one_item.batch_count, 3)

        # Verify batch 1 is unaffected
        batch_1_1 = self._get_batch_item(scene_one_item, 1, 1)
        log_input_expected_result("batch (1,1) line count", 2, batch_1_1.line_count)
        self.assertEqual(batch_1_1.line_count, 2)

        # Verify replaced batch has new line count
        batch_1_2 = self._get_batch_item(scene_one_item, 1, 2)
        log_input_expected_result("batch (1,2) line count", 5, batch_1_2.line_count)
        self.assertEqual(batch_1_2.line_count, 5)

        # Verify batch 3 is unaffected
        batch_1_3 = self._get_batch_item(scene_one_item, 1, 3)
        log_input_expected_result("batch (1,3) line count", 3, batch_1_3.line_count)
        self.assertEqual(batch_1_3.line_count, 3)

        # Verify scene 2 is completely unaffected
        scene_two_item = self._get_scene_item(viewmodel, 2)
        log_input_expected_result("scene 2 batch count", 2, scene_two_item.batch_count)
        self.assertEqual(scene_two_item.batch_count, 2)

    
    def test_delete_multiple_lines(self):
        """Test deleting multiple lines validates remaining lines and content"""
        base_counts = [[5, 4], [3, 2]]
        viewmodel, _ = self._create_viewmodel_with_counts(base_counts)
        viewmodel.clear_signal_history()

        # Delete lines 2 and 4 from batch (1,1), leaving lines 1, 3, 5
        update = ModelUpdate()
        update.lines.remove((1, 1, 2))
        update.lines.remove((1, 1, 4))

        update.ApplyToViewModel(viewmodel)

        scene_one_item = self._get_scene_item(viewmodel, 1)

        # Verify affected batch has correct line count
        batch_1_1 = self._get_batch_item(scene_one_item, 1, 1)
        log_input_expected_result("batch (1,1) line count", 3, batch_1_1.line_count)
        self.assertEqual(batch_1_1.line_count, 3)

        # Verify remaining lines have correct text
        # After deleting lines 2 and 4, the remaining lines (originally 1, 3, 5)
        # are now at positions 1, 2, 3 but retain their original content
        line_at_pos_1 = self._get_line_item(batch_1_1, 1, 1, 1)
        log_input_expected_result("line at position 1 text", "Scene 1 Batch 1 Line 1", line_at_pos_1.line_text)
        self.assertEqual(line_at_pos_1.line_text, "Scene 1 Batch 1 Line 1")

        line_at_pos_2 = self._get_line_item(batch_1_1, 1, 1, 2)
        log_input_expected_result("line at position 2 text", "Scene 1 Batch 1 Line 3", line_at_pos_2.line_text)
        self.assertEqual(line_at_pos_2.line_text, "Scene 1 Batch 1 Line 3")

        line_at_pos_3 = self._get_line_item(batch_1_1, 1, 1, 3)
        log_input_expected_result("line at position 3 text", "Scene 1 Batch 1 Line 5", line_at_pos_3.line_text)
        self.assertEqual(line_at_pos_3.line_text, "Scene 1 Batch 1 Line 5")

        # Verify other batches are unaffected
        batch_1_2 = self._get_batch_item(scene_one_item, 1, 2)
        log_input_expected_result("batch (1,2) line count", 4, batch_1_2.line_count)
        self.assertEqual(batch_1_2.line_count, 4)

        # Verify scene 2 is completely unaffected
        scene_two_item = self._get_scene_item(viewmodel, 2)
        log_input_expected_result("scene 2 batch count", 2, scene_two_item.batch_count)
        self.assertEqual(scene_two_item.batch_count, 2)

        batch_2_1 = self._get_batch_item(scene_two_item, 2, 1)
        log_input_expected_result("batch (2,1) line count", 3, batch_2_1.line_count)
        self.assertEqual(batch_2_1.line_count, 3)

        viewmodel.assert_signal_emitted(self, 'modelReset', expected_count=1)

    
    def test_large_realistic_model(self):
        """Test with a larger, more realistic subtitle structure"""
        # Simulate a typical 20-minute episode with ~200 lines
        # Organized into 10 scenes with varying batch sizes
        line_counts = [
            [5, 8, 6],      # Scene 1: 19 lines
            [10, 12],       # Scene 2: 22 lines
            [7, 9, 8],      # Scene 3: 24 lines
            [15, 10],       # Scene 4: 25 lines
            [6, 7, 8, 6],   # Scene 5: 27 lines
            [12, 11],       # Scene 6: 23 lines
            [8, 9, 7],      # Scene 7: 24 lines
            [10, 8, 6],     # Scene 8: 24 lines
            [5, 6, 5],      # Scene 9: 16 lines
            [4, 5, 3]       # Scene 10: 12 lines
        ]

        viewmodel, subtitles = self._create_viewmodel_with_counts(line_counts)

        root_item = viewmodel.getRootItem()
        log_input_expected_result("scene count", len(line_counts), root_item.rowCount())
        self.assertEqual(root_item.rowCount(), len(line_counts))

        total_lines = sum(sum(scene) for scene in line_counts)
        actual_lines = len(subtitles.originals or [])
        log_input_expected_result("total lines", total_lines, actual_lines)
        self.assertEqual(actual_lines, total_lines)

        # Verify complete structure integrity for all scenes
        for scene_index, expected_batches in enumerate(line_counts, start=1):
            scene_item = self._get_scene_item(viewmodel, scene_index)
            log_input_expected_result(f"scene {scene_index} batch count", len(expected_batches), scene_item.batch_count)
            self.assertEqual(scene_item.batch_count, len(expected_batches))

            # Verify each batch in detail
            for batch_index, expected_line_count in enumerate(expected_batches, start=1):
                batch_item = self._get_batch_item(scene_item, scene_index, batch_index)
                log_input_expected_result(
                    f"batch ({scene_index},{batch_index}) line count",
                    expected_line_count,
                    batch_item.line_count
                )
                self.assertEqual(batch_item.line_count, expected_line_count)

                # Spot check: verify first and last line in each batch have correct text
                first_line = self._get_line_item(batch_item, scene_index, batch_index, 1)
                expected_first = f"Scene {scene_index} Batch {batch_index} Line 1"
                log_input_expected_result(f"batch ({scene_index},{batch_index}) first line", expected_first, first_line.line_text)
                self.assertEqual(first_line.line_text, expected_first)

                if expected_line_count > 1:
                    last_line = self._get_line_item(batch_item, scene_index, batch_index, expected_line_count)
                    expected_last = f"Scene {scene_index} Batch {batch_index} Line {expected_line_count}"
                    log_input_expected_result(f"batch ({scene_index},{batch_index}) last line", expected_last, last_line.line_text)
                    self.assertEqual(last_line.line_text, expected_last)

    def test_realistic_update_on_large_model(self):
        """Test performing realistic updates on a larger model"""
        # Use a moderately large structure
        line_counts = [
            [8, 10, 7],     # Scene 1: lines 1-25
            [12, 15],       # Scene 2: lines 26-52
            [9, 11, 8, 6],  # Scene 3: lines 53-86
            [14, 10],       # Scene 4: lines 87-110
        ]

        viewmodel, _ = self._create_viewmodel_with_counts(line_counts)
        viewmodel.clear_signal_history()

        # Get actual global line numbers from the batches
        scene_1 = self._get_scene_item(viewmodel, 1)
        batch_1_1 = self._get_batch_item(scene_1, 1, 1)
        global_line_1 = self._get_line_numbers_in_batch(batch_1_1)[0]

        scene_3 = self._get_scene_item(viewmodel, 3)
        batch_3_2 = self._get_batch_item(scene_3, 3, 2)
        global_line_67 = self._get_line_numbers_in_batch(batch_3_2)[5]

        scene_4 = self._get_scene_item(viewmodel, 4)
        batch_4_2 = self._get_batch_item(scene_4, 4, 2)
        global_line_110 = self._get_line_numbers_in_batch(batch_4_2)[-1]

        # Perform a complex update touching multiple scenes
        update = ModelUpdate()
        # Update scene 1 summary
        update.scenes.update(1, {'summary': 'Scene 1 - Updated'})
        # Update batch (2,1) summary
        update.batches.update((2, 1), {'summary': 'Scene 2 Batch 1 - Updated'})
        # Update some line texts using actual global line numbers
        update.lines.update((1, 1, global_line_1), {'text': 'Updated first line'})
        update.lines.update((3, 2, global_line_67), {'text': 'Updated middle line'})
        update.lines.update((4, 2, global_line_110), {'text': 'Updated last line'})

        update.ApplyToViewModel(viewmodel)

        # Verify scene 1 update
        scene_1 = self._get_scene_item(viewmodel, 1)
        log_input_expected_result("scene 1 summary", 'Scene 1 - Updated', scene_1.summary)
        self.assertEqual(scene_1.summary, 'Scene 1 - Updated')

        # Verify batch (2,1) update
        scene_2 = self._get_scene_item(viewmodel, 2)
        batch_2_1 = self._get_batch_item(scene_2, 2, 1)
        log_input_expected_result("batch (2,1) summary", 'Scene 2 Batch 1 - Updated', batch_2_1.summary)
        self.assertEqual(batch_2_1.summary, 'Scene 2 Batch 1 - Updated')

        # Verify line updates
        batch_1_1 = self._get_batch_item(scene_1, 1, 1)
        updated_line_1 = cast(LineItem, batch_1_1.child(0, 0))
        log_input_expected_result(f"line ({global_line_1}) text", 'Updated first line', updated_line_1.line_text)
        self.assertEqual(updated_line_1.line_text, 'Updated first line')

        batch_3_2 = self._get_batch_item(scene_3, 3, 2)
        updated_line_67 = cast(LineItem, batch_3_2.child(5, 0))
        log_input_expected_result(f"line ({global_line_67}) text", 'Updated middle line', updated_line_67.line_text)
        self.assertEqual(updated_line_67.line_text, 'Updated middle line')

        batch_4_2 = self._get_batch_item(scene_4, 4, 2)
        updated_line_110 = cast(LineItem, batch_4_2.child(9, 0))
        log_input_expected_result(f"line ({global_line_110}) text", 'Updated last line', updated_line_110.line_text)
        self.assertEqual(updated_line_110.line_text, 'Updated last line')

        # Verify unaffected scenes maintained their structure
        log_input_expected_result("scene 4 batch count", 2, scene_4.batch_count)
        self.assertEqual(scene_4.batch_count, 2)

        batch_4_1 = self._get_batch_item(scene_4, 4, 1)
        log_input_expected_result("batch (4,1) line count", 14, batch_4_1.line_count)
        self.assertEqual(batch_4_1.line_count, 14)

    @unittest.skip("Test needs to be rewritten to properly simulate MergeScenesCommand")
    def test_merge_scenes_pattern(self):
        """Test the complex update pattern used by MergeScenesCommand"""
        # Create a structure with 5 scenes to make renumbering interesting
        base_counts = [[2, 2], [3], [1, 1], [2], [3, 1]]
        viewmodel, subtitles = self._create_viewmodel_with_counts(base_counts)
        viewmodel.clear_signal_history()

        # Simulate merging scenes 2 and 3 into scene 2
        # This is what MergeScenesCommand does:
        # 1. Merge the actual scene data in the subtitles model using the editor
        # 2. Update the viewmodel to reflect the changes

        # First, merge the scenes in the underlying data model (what the editor does)
        scene_2 = subtitles.GetScene(2)
        scene_3 = subtitles.GetScene(3)
        # Move scene 3's batches to scene 2
        for batch in scene_3.batches:
            scene_2.batches.append(batch)
            batch.scene = 2
        # Remove scene 3 from subtitles
        subtitles.scenes = [s for s in subtitles.scenes if s.number != 3]
        # Renumber later scenes in the data model
        for scene in subtitles.scenes:
            if scene.number == 4:
                scene.number = 3
            elif scene.number == 5:
                scene.number = 4

        # Now create the viewmodel update to reflect these data changes
        update = ModelUpdate()
        # Renumber later scenes in viewmodel (4→3, 5→4)
        update.scenes.update(4, {'number': 3})
        update.scenes.update(5, {'number': 4})
        # Replace scene 2 with updated scene
        update.scenes.replace(2, scene_2)
        # Remove scene 3 from viewmodel (already removed from data)
        update.scenes.removals = [3]

        update.ApplyToViewModel(viewmodel)

        # Verify final structure
        root_item = viewmodel.getRootItem()
        log_input_expected_result("final scene count", 4, root_item.rowCount())
        self.assertEqual(root_item.rowCount(), 4)

        # Verify scene 1 is unchanged
        scene_1 = self._get_scene_item(viewmodel, 1)
        log_input_expected_result("scene 1 batch count", 2, scene_1.batch_count)
        self.assertEqual(scene_1.batch_count, 2)

        # Verify scene 2 is the merged scene (now has 3 batches: 3+1+1 from original scenes 2+3)
        scene_2 = self._get_scene_item(viewmodel, 2)
        log_input_expected_result("scene 2 batch count", 3, scene_2.batch_count)
        self.assertEqual(scene_2.batch_count, 3)

        batch_2_1 = self._get_batch_item(scene_2, 2, 1)
        log_input_expected_result("batch (2,1) line count", 3, batch_2_1.line_count)
        self.assertEqual(batch_2_1.line_count, 3)

        # Verify scene 3 no longer exists (was removed)
        # But scene 4 (originally scene 4) should now be scene 3
        scene_3 = self._get_scene_item(viewmodel, 3)
        log_input_expected_result("scene 3 (was scene 4) batch count", 1, scene_3.batch_count)
        self.assertEqual(scene_3.batch_count, 1)

        batch_3_1 = self._get_batch_item(scene_3, 3, 1)
        log_input_expected_result("batch (3,1) line count", 2, batch_3_1.line_count)
        self.assertEqual(batch_3_1.line_count, 2)

        # Verify scene 4 (originally scene 5) structure
        scene_4 = self._get_scene_item(viewmodel, 4)
        log_input_expected_result("scene 4 (was scene 5) batch count", 2, scene_4.batch_count)
        self.assertEqual(scene_4.batch_count, 2)

        viewmodel.assert_signal_emitted(self, 'modelReset', expected_count=1)

    def test_merge_batches_pattern(self):
        """Test the update pattern used by MergeBatchesCommand"""
        # Create a scene with multiple batches to merge
        base_counts = [[3, 4, 2, 5], [2]]
        viewmodel, _ = self._create_viewmodel_with_counts(base_counts)
        viewmodel.clear_signal_history()

        # Simulate merging batches 2, 3, 4 in scene 1 into batch 2
        # MergeBatchesCommand does:
        # 1. Replace batch 2 with merged batch (containing all lines from batches 2,3,4)
        # 2. Remove batches 3 and 4

        # Create merged batch with combined line count (4+2+5=11 lines)
        merged_batch = self._create_batch(1, 2, 11, 4, timedelta(seconds=10))

        update = ModelUpdate()
        update.batches.replace((1, 2), merged_batch)
        update.batches.remove((1, 3))
        update.batches.remove((1, 4))

        update.ApplyToViewModel(viewmodel)

        # Verify final structure
        scene_1 = self._get_scene_item(viewmodel, 1)
        log_input_expected_result("scene 1 batch count", 2, scene_1.batch_count)
        self.assertEqual(scene_1.batch_count, 2)

        # Verify batch 1 is unchanged
        batch_1_1 = self._get_batch_item(scene_1, 1, 1)
        log_input_expected_result("batch (1,1) line count", 3, batch_1_1.line_count)
        self.assertEqual(batch_1_1.line_count, 3)

        # Verify batch 2 is the merged batch
        batch_1_2 = self._get_batch_item(scene_1, 1, 2)
        log_input_expected_result("batch (1,2) line count", 11, batch_1_2.line_count)
        self.assertEqual(batch_1_2.line_count, 11)

        # Verify batches 3 and 4 are gone (can't access them)
        # The scene should only have 2 batches now
        log_input_expected_result("scene 1 child count", 2, scene_1.rowCount())
        self.assertEqual(scene_1.rowCount(), 2)

        # Verify scene 2 is completely unaffected
        scene_2 = self._get_scene_item(viewmodel, 2)
        log_input_expected_result("scene 2 batch count", 1, scene_2.batch_count)
        self.assertEqual(scene_2.batch_count, 1)

        viewmodel.assert_signal_emitted(self, 'modelReset', expected_count=1)

    
    def test_split_batch_pattern(self):
        """Test the update pattern used by SplitBatchCommand"""
        # Create a scene with a large batch to split
        base_counts = [[8, 6], [3]]
        viewmodel, _subtitles = self._create_viewmodel_with_counts(base_counts)
        viewmodel.clear_signal_history()

        # Simulate splitting batch (1,1) at line 4
        # Lines 1-3 stay in batch 1, lines 4-8 move to new batch 2
        # Old batch 2 becomes batch 3
        # SplitBatchCommand would:
        # 1. Remove lines 4-8 from batch 1
        # 2. Renumber old batch 2 to batch 3
        # 3. Add new batch 2 with lines 4-8

        # Create the new batch 2 (lines 4-8)
        new_batch_2 = self._create_batch(1, 2, 5, 4, timedelta(seconds=10))

        update = ModelUpdate()
        # Remove lines 4-8 from batch 1
        update.lines.remove((1, 1, 4))
        update.lines.remove((1, 1, 5))
        update.lines.remove((1, 1, 6))
        update.lines.remove((1, 1, 7))
        update.lines.remove((1, 1, 8))
        # Renumber old batch 2 to batch 3
        update.batches.update((1, 2), {'number': 3})
        # Add new batch 2
        update.batches.add((1, 2), new_batch_2)

        update.ApplyToViewModel(viewmodel)

        # Verify final structure
        scene_1 = self._get_scene_item(viewmodel, 1)
        log_input_expected_result("scene 1 batch count", 3, scene_1.batch_count)
        self.assertEqual(scene_1.batch_count, 3)

        # Verify batch 1 now has only 3 lines
        batch_1_1 = self._get_batch_item(scene_1, 1, 1)
        log_input_expected_result("batch (1,1) line count", 3, batch_1_1.line_count)
        self.assertEqual(batch_1_1.line_count, 3)

        # Verify new batch 2 has 5 lines
        batch_1_2 = self._get_batch_item(scene_1, 1, 2)
        log_input_expected_result("batch (1,2) line count", 5, batch_1_2.line_count)
        self.assertEqual(batch_1_2.line_count, 5)

        # Verify old batch 2 is now batch 3 with 6 lines
        batch_1_3 = self._get_batch_item(scene_1, 1, 3)
        log_input_expected_result("batch (1,3) line count", 6, batch_1_3.line_count)
        self.assertEqual(batch_1_3.line_count, 6)

        # Verify scene 2 unaffected
        scene_2 = self._get_scene_item(viewmodel, 2)
        log_input_expected_result("scene 2 batch count", 1, scene_2.batch_count)
        self.assertEqual(scene_2.batch_count, 1)

        viewmodel.assert_signal_emitted(self, 'modelReset', expected_count=1)

    def test_split_scene_pattern(self):
        """Test the update pattern used by SplitSceneCommand"""
        # Create scenes where we'll split scene 1
        base_counts = [[4, 5, 3], [2], [6]]
        viewmodel, _subtitles = self._create_viewmodel_with_counts(base_counts)
        viewmodel.clear_signal_history()

        # Simulate splitting scene 1 at batch 2
        # Batches 1 stays in scene 1, batches 2-3 move to new scene 2
        # Old scenes 2,3 become scenes 3,4
        # SplitSceneCommand would:
        # 1. Renumber old scene 2→3, scene 3→4
        # 2. Remove batches 2,3 from scene 1
        # 3. Add new scene 2 with those batches

        # Create new scene 2 with batches from old scene 1
        new_scene_2 = self._create_scene(2, [5, 3], 5, timedelta(seconds=10))

        update = ModelUpdate()
        # Renumber later scenes
        update.scenes.update(2, {'number': 3})
        update.scenes.update(3, {'number': 4})
        # Remove batches 2 and 3 from scene 1
        update.batches.remove((1, 2))
        update.batches.remove((1, 3))
        # Add new scene 2
        update.scenes.add(2, new_scene_2)

        update.ApplyToViewModel(viewmodel)

        # Verify final structure
        root_item = viewmodel.getRootItem()
        log_input_expected_result("total scene count", 4, root_item.rowCount())
        self.assertEqual(root_item.rowCount(), 4)

        # Verify scene 1 now has only 1 batch
        scene_1 = self._get_scene_item(viewmodel, 1)
        log_input_expected_result("scene 1 batch count", 1, scene_1.batch_count)
        self.assertEqual(scene_1.batch_count, 1)

        batch_1_1 = self._get_batch_item(scene_1, 1, 1)
        log_input_expected_result("batch (1,1) line count", 4, batch_1_1.line_count)
        self.assertEqual(batch_1_1.line_count, 4)

        # Verify new scene 2 has 2 batches
        scene_2 = self._get_scene_item(viewmodel, 2)
        log_input_expected_result("scene 2 batch count", 2, scene_2.batch_count)
        self.assertEqual(scene_2.batch_count, 2)

        # Verify old scene 2 is now scene 3
        scene_3 = self._get_scene_item(viewmodel, 3)
        log_input_expected_result("scene 3 (was scene 2) batch count", 1, scene_3.batch_count)
        self.assertEqual(scene_3.batch_count, 1)

        # Verify old scene 3 is now scene 4
        scene_4 = self._get_scene_item(viewmodel, 4)
        log_input_expected_result("scene 4 (was scene 3) batch count", 1, scene_4.batch_count)
        self.assertEqual(scene_4.batch_count, 1)

        batch_4_1 = self._get_batch_item(scene_4, 4, 1)
        log_input_expected_result("batch (4,1) line count", 6, batch_4_1.line_count)
        self.assertEqual(batch_4_1.line_count, 6)

        viewmodel.assert_signal_emitted(self, 'modelReset', expected_count=1)

    def test_multiple_updates_in_sequence(self):
        """Test applying multiple updates sequentially"""
        base_counts = [[3, 3], [2, 2]]
        viewmodel, _subtitles = self._create_viewmodel_with_counts(base_counts)
        viewmodel.clear_signal_history()

        # Update 1: Edit scene summary
        update1 = ModelUpdate()
        update1.scenes.update(1, {'summary': 'First update'})
        update1.ApplyToViewModel(viewmodel)

        # Update 2: Edit batch summary
        update2 = ModelUpdate()
        update2.batches.update((1, 1), {'summary': 'Second update'})
        update2.ApplyToViewModel(viewmodel)

        # Update 3: Edit line text
        update3 = ModelUpdate()
        update3.lines.update((1, 1, 1), {'text': 'Third update'})
        update3.ApplyToViewModel(viewmodel)

        # Verify all updates were applied
        scene_one_item = self._get_scene_item(viewmodel, 1)
        log_input_expected_result("scene 1 summary", 'First update', scene_one_item.summary)
        self.assertEqual(scene_one_item.summary, 'First update')

        batch_one_item = self._get_batch_item(scene_one_item, 1, 1)
        log_input_expected_result("batch (1,1) summary", 'Second update', batch_one_item.summary)
        self.assertEqual(batch_one_item.summary, 'Second update')

        line_item = self._get_line_item(batch_one_item, 1, 1, 1)
        log_input_expected_result("line (1,1,1) text", 'Third update', line_item.line_text)
        self.assertEqual(line_item.line_text, 'Third update')

    def test_complex_multi_operation_update(self):
        """Test a complex update with multiple operations at once"""
        # Scene 1: [3, 3, 3] = lines 1-9
        # Scene 2: [2, 2] = lines 10-13
        # Scene 3: [4] = lines 14-17
        base_counts = [[3, 3, 3], [2, 2], [4]]
        viewmodel, _ = self._create_viewmodel_with_counts(base_counts)
        viewmodel.clear_signal_history()

        # Get actual global line numbers
        scene_one_item = self._get_scene_item(viewmodel, 1)
        batch_1_1 = self._get_batch_item(scene_one_item, 1, 1)
        global_line_1 = self._get_line_numbers_in_batch(batch_1_1)[0]

        scene_three_item = self._get_scene_item(viewmodel, 3)
        batch_3_1 = self._get_batch_item(scene_three_item, 3, 1)
        global_line_15 = self._get_line_numbers_in_batch(batch_3_1)[1]

        # Perform multiple updates in one ModelUpdate (scene, batch, and line updates)
        update = ModelUpdate()
        # Edit scene 1 summary
        update.scenes.update(1, {'summary': 'Updated scene 1'})
        # Edit batch (1,2) summary
        update.batches.update((1, 2), {'summary': 'Updated batch 1,2'})
        # Edit line using global line numbers
        update.lines.update((1, 1, global_line_1), {'text': 'Updated line text'})
        # Update line in scene 3
        update.lines.update((3, 1, global_line_15), {'text': 'Another updated line'})

        update.ApplyToViewModel(viewmodel)

        # Verify scene update
        scene_one_item = self._get_scene_item(viewmodel, 1)
        log_input_expected_result("scene 1 summary", 'Updated scene 1', scene_one_item.summary)
        self.assertEqual(scene_one_item.summary, 'Updated scene 1')

        # Verify batch update
        batch_item = self._get_batch_item(scene_one_item, 1, 2)
        log_input_expected_result("batch (1,2) summary", 'Updated batch 1,2', batch_item.summary)
        self.assertEqual(batch_item.summary, 'Updated batch 1,2')

        # Verify first line update
        batch_one_item_scene1 = self._get_batch_item(scene_one_item, 1, 1)
        line_one_item = self._get_line_item(batch_one_item_scene1, 1, 1, 1)
        log_input_expected_result("line (1,1,1) text", 'Updated line text', line_one_item.line_text)
        self.assertEqual(line_one_item.line_text, 'Updated line text')

        # Verify second line update in scene 3
        batch_three_one_item = self._get_batch_item(scene_three_item, 3, 1)
        line_3_1_2_updated = cast(LineItem, batch_three_one_item.child(1, 0))
        log_input_expected_result("line (3,1,2) text", 'Another updated line', line_3_1_2_updated.line_text)
        self.assertEqual(line_3_1_2_updated.line_text, 'Another updated line')
