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
        Helper to retrieve a scene item from the view model.
        Returns the SceneItem or None if not found or wrong type.
        """
        root_item = viewmodel.getRootItem()
        scene_item_qt = root_item.child(scene_number - 1, 0)

        log_input_expected_result(f"scene {scene_number} exists", True, scene_item_qt is not None)
        self.assertIsNotNone(scene_item_qt)

        log_input_expected_result(f"scene {scene_number} type", SceneItem, type(scene_item_qt))
        self.assertEqual(type(scene_item_qt), SceneItem)

        return cast(SceneItem, scene_item_qt)

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
