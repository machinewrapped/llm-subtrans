from datetime import timedelta
from typing import cast

from PySide6.QtCore import QCoreApplication

from GuiSubtrans.ViewModel.BatchItem import BatchItem
from GuiSubtrans.ViewModel.LineItem import LineItem
from GuiSubtrans.ViewModel.SceneItem import SceneItem
from GuiSubtrans.ViewModel.ViewModel import ProjectViewModel
from GuiSubtrans.ViewModel.ViewModelUpdate import ModelUpdate
from PySubtrans.Helpers.TestCases import BuildSubtitlesFromLineCounts, SubtitleTestCase
from PySubtrans.Helpers.Tests import log_input_expected_result
from PySubtrans.SubtitleLine import SubtitleLine
from PySubtrans.Subtitles import Subtitles


class ProjectViewModelTests(SubtitleTestCase):
    _qt_app : QCoreApplication|None = None

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        if QCoreApplication.instance() is None:
            cls._qt_app = QCoreApplication([])
        else:
            cls._qt_app = QCoreApplication.instance()

    def test_create_model_from_helper_subtitles(self) -> None:
        line_counts : list[list[int]] = [[3, 2], [1, 1, 2]]
        subtitles : Subtitles = BuildSubtitlesFromLineCounts(line_counts)

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

            scene_item : SceneItem = cast(SceneItem, scene_item_qt)
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

                batch_item : BatchItem = cast(BatchItem, batch_item_qt)
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

                    line_item : LineItem = cast(LineItem, line_item_qt)
                    expected_text = f"Scene {scene_index} Batch {batch_index} Line {line_row + 1}"
                    log_input_expected_result(
                        f"line ({scene_index},{batch_index},{line_row + 1}) text",
                        expected_text,
                        line_item.line_text
                    )
                    self.assertEqual(line_item.line_text, expected_text)

    def test_model_update_apply_changes(self) -> None:
        base_counts : list[list[int]] = [[2, 2], [1, 1]]
        subtitles : Subtitles = BuildSubtitlesFromLineCounts(base_counts)

        viewmodel = ProjectViewModel()
        viewmodel.CreateModel(subtitles)

        initial_scene_count = viewmodel.rowCount()
        log_input_expected_result("initial scene count", len(base_counts), initial_scene_count)
        self.assertEqual(initial_scene_count, len(base_counts))

        update = ModelUpdate()
        update.scenes.update(1, {'summary': 'Scene 1 (edited)'})
        update.batches.update((1, 1), {'summary': 'Scene 1 Batch 1 (edited)'})
        update.lines.update((1, 1, 1), {'text': 'Scene 1 Batch 1 Line 1 (edited)'})
        update.lines.remove((1, 1, 2))

        next_line_number = max((line.number for line in subtitles.originals or []), default=0) + 1

        new_line = SubtitleLine.Construct(
            next_line_number,
            timedelta(seconds=90),
            timedelta(seconds=91),
            'Scene 1 Batch 1 Line New',
            {}
        )
        update.lines.add((1, 1, new_line.number), new_line)
        next_line_number += 1

        new_batch_scene : Subtitles = BuildSubtitlesFromLineCounts([[2]])
        new_batch = new_batch_scene.GetScene(1).GetBatch(1)
        new_batch.scene = 1
        new_batch.number = len(subtitles.GetScene(1).batches) + 1
        new_batch.summary = f"Scene 1 Batch {new_batch.number}"
        for line in new_batch.originals:
            line.number = next_line_number
            line.start = line.start + timedelta(seconds=120)
            line.end = line.end + timedelta(seconds=120)
            next_line_number += 1
        update.batches.add((1, new_batch.number), new_batch)

        update.batches.remove((2, 2))

        extra_scene_subtitles : Subtitles = BuildSubtitlesFromLineCounts([[1, 1]])
        new_scene = extra_scene_subtitles.GetScene(1)
        new_scene.number = initial_scene_count + 1
        new_scene.summary = f"Scene {new_scene.number}"
        for batch_index, batch in enumerate(new_scene.batches, start=1):
            batch.scene = new_scene.number
            batch.number = batch_index
            batch.summary = f"Scene {new_scene.number} Batch {batch_index}"
            for line in batch.originals:
                line.number = next_line_number
                line.start = line.start + timedelta(seconds=180)
                line.end = line.end + timedelta(seconds=180)
                next_line_number += 1
        update.scenes.add(new_scene.number, new_scene)

        update.ApplyToViewModel(viewmodel)

        root_item = viewmodel.getRootItem()
        final_scene_count = root_item.rowCount()
        log_input_expected_result("final scene count", initial_scene_count + 1, final_scene_count)
        self.assertEqual(final_scene_count, initial_scene_count + 1)

        scene_one_item_qt = root_item.child(0, 0)
        self.assertIsNotNone(scene_one_item_qt)
        if scene_one_item_qt is None:
            return
        log_input_expected_result("scene 1 type after update", SceneItem, type(scene_one_item_qt))
        self.assertEqual(type(scene_one_item_qt), SceneItem)
        scene_one_item : SceneItem = cast(SceneItem, scene_one_item_qt)

        log_input_expected_result("scene 1 summary after update", 'Scene 1 (edited)', scene_one_item.summary)
        self.assertEqual(scene_one_item.summary, 'Scene 1 (edited)')

        expected_scene_one_batches = len(base_counts[0]) + 1
        log_input_expected_result(
            "scene 1 batch count after update",
            expected_scene_one_batches,
            scene_one_item.batch_count
        )
        self.assertEqual(scene_one_item.batch_count, expected_scene_one_batches)

        batch_one_item_qt = scene_one_item.child(0, 0)
        self.assertIsNotNone(batch_one_item_qt)
        if batch_one_item_qt is None:
            return
        log_input_expected_result("batch (1,1) type", BatchItem, type(batch_one_item_qt))
        self.assertEqual(type(batch_one_item_qt), BatchItem)
        batch_one_item : BatchItem = cast(BatchItem, batch_one_item_qt)

        log_input_expected_result(
            "batch (1,1) summary after update",
            'Scene 1 Batch 1 (edited)',
            batch_one_item.summary
        )
        self.assertEqual(batch_one_item.summary, 'Scene 1 Batch 1 (edited)')

        log_input_expected_result("batch (1,1) line count", 2, batch_one_item.line_count)
        self.assertEqual(batch_one_item.line_count, 2)

        updated_line_item_qt = batch_one_item.child(0, 0)
        self.assertIsNotNone(updated_line_item_qt)
        if updated_line_item_qt is None:
            return
        log_input_expected_result("line (1,1,1) type", LineItem, type(updated_line_item_qt))
        self.assertEqual(type(updated_line_item_qt), LineItem)
        updated_line_item : LineItem = cast(LineItem, updated_line_item_qt)

        log_input_expected_result(
            "updated line text",
            'Scene 1 Batch 1 Line 1 (edited)',
            updated_line_item.line_text
        )
        self.assertEqual(updated_line_item.line_text, 'Scene 1 Batch 1 Line 1 (edited)')

        new_line_item_qt = batch_one_item.child(1, 0)
        self.assertIsNotNone(new_line_item_qt)
        if new_line_item_qt is None:
            return
        log_input_expected_result("new line type", LineItem, type(new_line_item_qt))
        self.assertEqual(type(new_line_item_qt), LineItem)
        new_line_item : LineItem = cast(LineItem, new_line_item_qt)

        log_input_expected_result(
            "new line text",
            'Scene 1 Batch 1 Line New',
            new_line_item.line_text
        )
        self.assertEqual(new_line_item.line_text, 'Scene 1 Batch 1 Line New')

        scene_two_item_qt = root_item.child(1, 0)
        self.assertIsNotNone(scene_two_item_qt)
        if scene_two_item_qt is None:
            return
        log_input_expected_result("scene 2 type after update", SceneItem, type(scene_two_item_qt))
        self.assertEqual(type(scene_two_item_qt), SceneItem)
        scene_two_item : SceneItem = cast(SceneItem, scene_two_item_qt)

        log_input_expected_result(
            "scene 2 batch count after removal",
            len(base_counts[1]) - 1,
            scene_two_item.batch_count
        )
        self.assertEqual(scene_two_item.batch_count, len(base_counts[1]) - 1)

        scene_three_item_qt = root_item.child(2, 0)
        self.assertIsNotNone(scene_three_item_qt)
        if scene_three_item_qt is None:
            return
        log_input_expected_result("scene 3 type", SceneItem, type(scene_three_item_qt))
        self.assertEqual(type(scene_three_item_qt), SceneItem)
        scene_three_item : SceneItem = cast(SceneItem, scene_three_item_qt)

        log_input_expected_result("scene 3 number", 3, scene_three_item.number)
        self.assertEqual(scene_three_item.number, 3)

        log_input_expected_result("scene 3 batch count", 2, scene_three_item.batch_count)
        self.assertEqual(scene_three_item.batch_count, 2)

