from __future__ import annotations
from typing import Any

from GuiSubtrans.Commands.AutoSplitBatchCommand import AutoSplitBatchCommand
from GuiSubtrans.Commands.MergeBatchesCommand import MergeBatchesCommand
from GuiSubtrans.Commands.MergeScenesCommand import MergeScenesCommand
from GuiSubtrans.Commands.SplitBatchCommand import SplitBatchCommand
from GuiSubtrans.Commands.SplitSceneCommand import SplitSceneCommand
from GuiSubtrans.ProjectDataModel import ProjectDataModel

from GuiSubtrans.UnitTests.DataModelHelpers import CreateTestDataModelBatched
from PySubtrans.Helpers.TestCases import SubtitleTestCase
from PySubtrans.Helpers.Tests import log_input_expected_result, log_test_name
from PySubtrans.Subtitles import Subtitles
from PySubtrans.UnitTests.TestData.chinese_dinner import chinese_dinner_data

class MergeSplitCommandsTests(SubtitleTestCase):
    command_test_cases = [
        {
            'data': chinese_dinner_data,
            'tests' : [
                {
                    'test': 'MergeSceneCommandTest',
                    'scene_numbers': [2, 3],
                    'expected_scene_count': 3,
                    'expected_merged_scene_numbers': [1, 2, 3],
                    'expected_merged_linecounts': [30, 31, 3],
                    'expected_merged_scene_batches': [1, 2, 3],
                    'expected_merged_scene_sizes': [3, 3, 2],
                },
                {
                    'test': 'MergeSceneCommandTest',
                    'scene_numbers': [1, 2,3],
                    'expected_scene_count': 2,
                    'expected_merged_scene_numbers': [1, 2],
                    'expected_merged_linecounts': [61, 3],
                    'expected_merged_scene_batches': [1, 2, 3, 4, 5],
                    'expected_merged_scene_sizes': [5, 2],
                },
                {
                    'test': 'MergeSceneCommandTest',
                    'scene_numbers': [1, 2, 3, 4],
                    'expected_scene_count': 1,
                    'expected_merged_scene_numbers': [1],
                    'expected_merged_linecounts': [64],
                    'expected_merged_scene_batches': [1, 2, 3, 4, 5, 6],
                    'expected_merged_scene_sizes': [7],
                },
                {
                    'test': 'MergeBatchesCommandTest',
                    'scene_number': 2,
                    'batch_numbers': [1, 2],
                    'expected_batch_count': 1,
                    'expected_batch_numbers': [1],
                    'expeected_batch_sizes': [3],
                    'expected_batch_sizes': [25]
                },
                {
                    'test': 'MergeScenesMergeBatchesCommandTest',
                    'scene_numbers': [1, 2, 3],
                    'batch_numbers': [2, 3, 4],
                    'expected_scene_count': 2,
                    'expected_scene_numbers': [1, 2],
                    'expected_scene_sizes': [3, 1],
                    'expected_scene_linecounts': [61, 3],
                    'expected_scene_batches': [[1,2,3], [1]],
                    'expected_scene_batch_sizes': [[14, 41, 6], [3]]
                },
                {
                    'test': 'MergeSplitScenesCommandTest',
                    'scene_numbers': [1,2,3,4],
                    'expected_merge_scene_count': 1,
                    'expected_merge_scene_numbers': [1],
                    'expected_merge_scene_linecount': 64,
                    'expected_merge_scene_batches': [1, 2, 3, 4, 5, 6],
                    'split_scene_batch_number': 4,
                    'expected_split_scene_count': 2,
                    'expected_split_scene_numbers': [1, 2],
                    'expected_split_scene_batches': [[1, 2, 3], [1, 2, 3]],
                    'expected_split_scene_linecount': [42, 22],
                    'expected_split_first_lines': [
                        (1,"いつものように食事が終わるまでは誰も入れないでくれ.", "As usual, don't let anyone in until the meal is over."),
                        (43, "いくらで雇われた.", "How much were you hired for?")
                        ]
                },
                {
                    'test': 'SplitBatchCommandTest',
                    'batch_number': (1,1),
                    'split_line_number': 5,
                    'expected_batch_count': 3,
                    'expected_batch_numbers': [1, 2, 3],
                    'expected_batch_sizes': [4, 10, 16],
                    'expected_batch_first_lines': [
                        (1, "いつものように食事が終わるまでは誰も入れないでくれ.", "As usual, don't let anyone in until the meal is over."),
                        (5, "任せてください." ,"Leave it to me."),
                        (15, "俺は肩にだぞ.", "I'm on the shoulder.")
                    ]
                },
                {
                    'test': 'AutoSplitBatchCommandTest',
                    'min_batch_size': 5,
                    'batch_number': (1,2),
                    'expected_batch_count': 3,
                    'expected_batch_numbers': [1, 2, 3],
                    'expected_batch_sizes': [14, 8, 8],
                    'expected_batch_first_lines': [
                        (1, "いつものように食事が終わるまでは誰も入れないでくれ.", "As usual, don't let anyone in until the meal is over."),
                        (15, "俺は肩にだぞ." ,"I'm on the shoulder."),
                        (23, "遠慮するな.", "Don't hold back.")
                    ],
                    'expected_batch_line_numbers': [
                        [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14],
                        [15, 16, 17, 18, 19, 20, 21, 22],
                        [23, 24, 25, 26, 27, 28, 29, 30]
                    ]
                }
            ]
        }
    ]

    def test_Commands(self):
        for test_case in self.command_test_cases:
            data = test_case['data']
            log_test_name(f"Testing commands on {data.get('movie_name')}")

            datamodel = CreateTestDataModelBatched(data, options=self.options)
            self.assertIsNotNone(datamodel)
            self.assertIsNotNone(datamodel.project)
            assert datamodel.project is not None  # Type narrowing for PyLance
            self.assertIsNotNone(datamodel.project.subtitles)
            
            subtitles: Subtitles = datamodel.project.subtitles

            for command_data in test_case['tests']:
                test: str = command_data['test']

                with self.subTest(test):
                    log_test_name(f"{test} test")
                    if test == 'MergeSceneCommandTest':
                        self.MergeSceneCommandTest(subtitles, datamodel, command_data)
                    elif test == 'MergeBatchesCommandTest':
                        self.MergeBatchesCommandTest(subtitles, datamodel, command_data)
                    elif test == 'MergeScenesMergeBatchesCommandTest':
                        self.MergeScenesMergeBatchesCommandTest(subtitles, datamodel, command_data)
                    elif test == 'MergeSplitScenesCommandTest':
                        self.MergeSplitScenesCommandTest(subtitles, datamodel, command_data)
                    elif test == 'SplitBatchCommandTest':
                        self.SplitBatchCommandTest(subtitles, datamodel, command_data)
                    elif test == 'AutoSplitBatchCommandTest':
                        self.AutoSplitBatchCommandTest(subtitles, datamodel, command_data)
                    else:
                        self.fail(f"Unknown test type: {test}")

    def MergeSceneCommandTest(self, file: Subtitles, datamodel: ProjectDataModel, test_data: dict[str, Any]) -> None:
        merge_scene_numbers = test_data['scene_numbers']

        undo_expected_scene_count = len(file.scenes)
        undo_expected_scene_numbers = [scene.number for scene in file.scenes]
        undo_expected_scene_sizes = [scene.size for scene in file.scenes]
        undo_expected_scene_linecounts = [scene.linecount for scene in file.scenes]
        undo_expected_scene_batches = [[batch.number for batch in scene.batches] for scene in file.scenes]

        merge_scenes_command = MergeScenesCommand(merge_scene_numbers, datamodel)
        self.assertTrue(merge_scenes_command.execute())

        expected_scene_count = test_data['expected_scene_count']
        expected_merged_scene_numbers = test_data['expected_merged_scene_numbers']
        expected_merged_linecounts = test_data['expected_merged_linecounts']
        expected_merged_scene_batches = test_data['expected_merged_scene_batches']

        merge_result_scene_numbers = [scene.number for scene in file.scenes]
        log_input_expected_result("Merged scenes", (expected_scene_count, expected_merged_scene_numbers), (len(file.scenes), merge_result_scene_numbers))
        self.assertEqual(len(file.scenes), expected_scene_count)
        self.assertSequenceEqual(merge_result_scene_numbers, expected_merged_scene_numbers)
        self.assertSequenceEqual([scene.linecount for scene in file.scenes], expected_merged_linecounts)

        merged_scene = file.GetScene(merge_scene_numbers[0])

        merged_scene_batch_numbers = [batch.number for batch in merged_scene.batches]
        log_input_expected_result("Merged scene batches", expected_merged_scene_batches, merged_scene_batch_numbers)
        self.assertSequenceEqual(merged_scene_batch_numbers, expected_merged_scene_batches)

        self.assertTrue(merge_scenes_command.can_undo)
        self.assertTrue(merge_scenes_command.undo())

        undo_merge_result_scene_numbers = [scene.number for scene in file.scenes]
        log_input_expected_result("Scenes after undo", (undo_expected_scene_count, undo_expected_scene_numbers), (len(file.scenes), undo_merge_result_scene_numbers))

        self.assertEqual(len(file.scenes), undo_expected_scene_count)
        self.assertSequenceEqual(undo_merge_result_scene_numbers, undo_expected_scene_numbers)
        self.assertSequenceEqual([scene.size for scene in file.scenes], undo_expected_scene_sizes)
        self.assertSequenceEqual([scene.linecount for scene in file.scenes], undo_expected_scene_linecounts)
        self.assertSequenceEqual([[batch.number for batch in scene.batches] for scene in file.scenes], undo_expected_scene_batches)

    def MergeBatchesCommandTest(self, file: Subtitles, datamodel: ProjectDataModel, test_data: dict[str, Any]) -> None:
        scene_number = test_data['scene_number']
        batch_numbers = test_data['batch_numbers']

        merge_scene = file.GetScene(scene_number)
        undo_expected_batch_count = merge_scene.size
        undo_expected_batch_numbers = [batch.number for batch in merge_scene.batches]
        undo_expected_batch_sizes = [batch.size for batch in merge_scene.batches]

        merge_batches_command = MergeBatchesCommand(scene_number, batch_numbers, datamodel)
        self.assertTrue(merge_batches_command.execute())

        expected_batch_count = test_data['expected_batch_count']
        expected_batch_numbers = test_data['expected_batch_numbers']
        expected_batch_sizes = test_data['expected_batch_sizes']

        merged_scene_batch_numbers = [batch.number for batch in merge_scene.batches]

        log_input_expected_result("Merged scene batches", (expected_batch_count, expected_batch_numbers), (len(merge_scene.batches), merged_scene_batch_numbers))
        self.assertEqual(len(merge_scene.batches), expected_batch_count)
        self.assertSequenceEqual(merged_scene_batch_numbers, expected_batch_numbers)
        self.assertSequenceEqual([batch.size for batch in merge_scene.batches], expected_batch_sizes)

        self.assertTrue(merge_batches_command.can_undo)
        self.assertTrue(merge_batches_command.undo())

        log_input_expected_result("Batches after undo", (undo_expected_batch_count, undo_expected_batch_numbers), (len(merge_scene.batches), [batch.number for batch in merge_scene.batches]))
        self.assertEqual(len(merge_scene.batches), undo_expected_batch_count)
        self.assertSequenceEqual([batch.number for batch in merge_scene.batches], undo_expected_batch_numbers)
        self.assertSequenceEqual([batch.size for batch in merge_scene.batches], undo_expected_batch_sizes)

    def MergeScenesMergeBatchesCommandTest(self, file: Subtitles, datamodel: ProjectDataModel, test_data: dict[str, Any]) -> None:
        # Merge scenes, then merge batches in the merged scenes, then undo both
        merge_scene_numbers = test_data['scene_numbers']
        merge_batch_numbers = test_data['batch_numbers']

        undo_expected_scene_count = len(file.scenes)
        undo_expected_scene_numbers = [scene.number for scene in file.scenes]
        undo_expected_scene_sizes = [scene.size for scene in file.scenes]
        undo_expected_scene_linecounts = [scene.linecount for scene in file.scenes]
        undo_expected_scene_batches = [[batch.number for batch in scene.batches] for scene in file.scenes]
        undo_expected_scene_batch_sizes = [[batch.size for batch in scene.batches] for scene in file.scenes]

        merge_scenes_command = MergeScenesCommand(merge_scene_numbers, datamodel)
        self.assertTrue(merge_scenes_command.execute())

        merge_batches_command = MergeBatchesCommand(merge_scene_numbers[0], merge_batch_numbers, datamodel)
        self.assertTrue(merge_batches_command.execute())

        expected_scene_count = test_data['expected_scene_count']
        expected_scene_numbers = test_data['expected_scene_numbers']
        expected_scene_sizes = test_data['expected_scene_sizes']
        expected_scene_linecounts = test_data['expected_scene_linecounts']
        expected_scene_batches = test_data['expected_scene_batches']
        expected_scene_batch_sizes = test_data['expected_scene_batch_sizes']

        log_input_expected_result("Merged scenes", (expected_scene_count, expected_scene_numbers), (len(file.scenes), [scene.number for scene in file.scenes]))
        self.assertEqual(len(file.scenes), expected_scene_count)
        self.assertSequenceEqual([scene.number for scene in file.scenes], expected_scene_numbers)
        self.assertSequenceEqual([scene.size for scene in file.scenes], expected_scene_sizes)
        self.assertSequenceEqual([scene.linecount for scene in file.scenes], expected_scene_linecounts)

        scene_batches = [[batch.number for batch in scene.batches] for scene in file.scenes]
        log_input_expected_result("Merged scene batches", expected_scene_batches, scene_batches)
        self.assertSequenceEqual(scene_batches, expected_scene_batches)
        scene_batch_sizes = [[batch.size for batch in scene.batches] for scene in file.scenes]
        log_input_expected_result("Merged scene batch sizes", expected_scene_batch_sizes, scene_batch_sizes)
        self.assertSequenceEqual(scene_batch_sizes, expected_scene_batch_sizes)

        self.assertTrue(merge_batches_command.can_undo)
        self.assertTrue(merge_batches_command.undo())

        self.assertTrue(merge_scenes_command.can_undo)
        self.assertTrue(merge_scenes_command.undo())

        undo_merge_result_scene_numbers = [scene.number for scene in file.scenes]
        log_input_expected_result("Scenes after undo", (undo_expected_scene_count, undo_expected_scene_numbers), (len(file.scenes), undo_merge_result_scene_numbers))

        self.assertEqual(len(file.scenes), undo_expected_scene_count)
        self.assertSequenceEqual(undo_merge_result_scene_numbers, undo_expected_scene_numbers)
        self.assertSequenceEqual([scene.size for scene in file.scenes], undo_expected_scene_sizes)
        self.assertSequenceEqual([scene.linecount for scene in file.scenes], undo_expected_scene_linecounts)
        self.assertSequenceEqual([[batch.number for batch in scene.batches] for scene in file.scenes], undo_expected_scene_batches)
        self.assertSequenceEqual([[batch.size for batch in scene.batches] for scene in file.scenes], undo_expected_scene_batch_sizes)

    def MergeSplitScenesCommandTest(self, file: Subtitles, datamodel: ProjectDataModel, test_data: dict[str, Any]) -> None:
        # Merge scenes, then split the merged scene, then undo both
        merge_scene_numbers = test_data['scene_numbers']
        split_scene_batch_number = test_data['split_scene_batch_number']

        undo_merge_expected_scene_count = len(file.scenes)
        undo_merge_expected_scene_numbers = [scene.number for scene in file.scenes]
        undo_merge_expected_scene_linecount = [scene.linecount for scene in file.scenes]
        undo_merge_expected_scene_batches = [[batch.number for batch in scene.batches] for scene in file.scenes]

        # Merge scenes
        merge_scenes_command = MergeScenesCommand(merge_scene_numbers, datamodel)
        self.assertTrue(merge_scenes_command.execute())

        expected_merge_scene_count = test_data['expected_merge_scene_count']
        expected_merge_scene_numbers = test_data['expected_merge_scene_numbers']
        expected_merge_scene_batches = test_data['expected_merge_scene_batches']
        expected_merge_scene_linecount = test_data['expected_merge_scene_linecount']

        log_input_expected_result("Merged scenes", (expected_merge_scene_count, expected_merge_scene_numbers), (len(file.scenes), [scene.number for scene in file.scenes]))
        self.assertEqual(len(file.scenes), expected_merge_scene_count)

        merged_scene = file.GetScene(merge_scene_numbers[0])
        merged_scene_batches = [batch.number for batch in merged_scene.batches]

        self.assertEqual(merged_scene.linecount, expected_merge_scene_linecount)

        log_input_expected_result("Merged scene batches", expected_merge_scene_batches, merged_scene_batches)
        self.assertSequenceEqual(merged_scene_batches, expected_merge_scene_batches)

        undo_split_expected_scene_count = len(file.scenes)
        undo_split_expected_scene_numbers = [scene.number for scene in file.scenes]
        undo_split_expected_scene_linecount = [scene.linecount for scene in file.scenes]
        undo_split_expected_scene_batches = [[(batch.number, batch.first_line_number) for batch in scene.batches] for scene in file.scenes]

        # Split the scene
        split_scenes_command = SplitSceneCommand(merge_scene_numbers[0], split_scene_batch_number, datamodel)
        self.assertTrue(split_scenes_command.execute())

        expected_split_scene_count = test_data['expected_split_scene_count']
        expected_split_scene_numbers = test_data['expected_split_scene_numbers']
        expected_split_scene_batches = test_data['expected_split_scene_batches']
        expected_split_scene_linecount = test_data['expected_split_scene_linecount']
        expected_split_first_lines = test_data['expected_split_first_lines']

        log_input_expected_result("Split scenes", (expected_split_scene_count, expected_split_scene_numbers), (len(file.scenes), [scene.number for scene in file.scenes]))
        self.assertEqual(len(file.scenes), expected_split_scene_count)
        self.assertSequenceEqual([scene.number for scene in file.scenes], expected_split_scene_numbers)
        self.assertEqual([scene.linecount for scene in file.scenes], expected_split_scene_linecount)

        split_scenes_batches = [[batch.number for batch in scene.batches] for scene in file.scenes]
        log_input_expected_result("Split scene batches", expected_split_scene_batches, split_scenes_batches)
        self.assertSequenceEqual(split_scenes_batches, expected_split_scene_batches)

        for i in range(len(expected_split_first_lines)):
            scene = file.scenes[i]
            first_original = scene.batches[0].originals[0].text
            first_translated = scene.batches[0].translated[0].text
            log_input_expected_result(f"Scene {scene.number} first line", expected_split_first_lines[i], (scene.first_line_number, first_original, first_translated))
            self.assertEqual(scene.first_line_number, expected_split_first_lines[i][0])
            self.assertEqual(first_original, expected_split_first_lines[i][1])
            self.assertEqual(first_translated, expected_split_first_lines[i][2])

        # Undo split scene
        self.assertTrue(split_scenes_command.can_undo)
        self.assertTrue(split_scenes_command.undo())

        log_input_expected_result("Scenes after undo split", (undo_split_expected_scene_count, undo_split_expected_scene_numbers), (len(file.scenes), [scene.number for scene in file.scenes]))
        self.assertEqual(len(file.scenes), undo_split_expected_scene_count)
        self.assertSequenceEqual([scene.number for scene in file.scenes], undo_split_expected_scene_numbers)
        self.assertSequenceEqual([scene.linecount for scene in file.scenes], undo_split_expected_scene_linecount)
        self.assertSequenceEqual([[(batch.number, batch.first_line_number) for batch in scene.batches] for scene in file.scenes], undo_split_expected_scene_batches)

        # Undo merge scene
        self.assertTrue(merge_scenes_command.can_undo)
        self.assertTrue(merge_scenes_command.undo())

        log_input_expected_result("Scenes after undo merge", (undo_merge_expected_scene_count, undo_merge_expected_scene_numbers), (len(file.scenes), [scene.number for scene in file.scenes]))
        self.assertEqual(len(file.scenes), undo_merge_expected_scene_count)
        self.assertSequenceEqual([scene.number for scene in file.scenes], undo_merge_expected_scene_numbers)
        self.assertSequenceEqual([scene.linecount for scene in file.scenes], undo_merge_expected_scene_linecount)
        self.assertSequenceEqual([[batch.number for batch in scene.batches] for scene in file.scenes], undo_merge_expected_scene_batches)

    def SplitBatchCommandTest(self, file: Subtitles, datamodel: ProjectDataModel, test_data: dict[str, Any]) -> None:
        scene_number, batch_number = test_data['batch_number']
        split_line_number = test_data['split_line_number']

        scene = file.GetScene(scene_number)

        undo_expected_batch_count = len(scene.batches)
        undo_expected_batch_numbers = [batch.number for batch in scene.batches]
        undo_expected_batch_sizes = [batch.size for batch in scene.batches]
        undo_expected_batch_first_lines = [(batch.first_line_number, batch.originals[0].text, batch.translated[0].text) for batch in scene.batches]

        split_batch_command = SplitBatchCommand(scene_number, batch_number, split_line_number, split_line_number, datamodel=datamodel)
        self.assertTrue(split_batch_command.execute())

        expected_batch_count = test_data['expected_batch_count']
        expected_batch_numbers = test_data['expected_batch_numbers']
        expected_batch_sizes = test_data['expected_batch_sizes']
        expected_batch_first_lines = test_data['expected_batch_first_lines']

        log_input_expected_result("Split batch count", expected_batch_count, len(scene.batches))
        self.assertEqual(len(scene.batches), expected_batch_count)

        split_scene_batches = [batch.number for batch in scene.batches]
        log_input_expected_result("Split batch numbers", expected_batch_numbers, split_scene_batches)
        self.assertSequenceEqual(split_scene_batches, expected_batch_numbers)

        split_scene_batch_sizes = [batch.size for batch in scene.batches]
        log_input_expected_result("Split batch sizes", expected_batch_sizes, split_scene_batch_sizes)
        self.assertSequenceEqual(split_scene_batch_sizes, expected_batch_sizes)

        for i in range(len(scene.batches)):
            batch = scene.batches[i]
            expected_line_number, expected_original, expected_translated = expected_batch_first_lines[i]
            log_input_expected_result(f"Batch {batch.number} first line", (expected_line_number, expected_original), (batch.first_line_number, batch.originals[0].text))
            self.assertEqual(batch.first_line_number, expected_line_number)
            self.assertEqual(batch.originals[0].text, expected_original)
            self.assertEqual(batch.translated[0].text, expected_translated)

        self.assertTrue(split_batch_command.can_undo)
        self.assertTrue(split_batch_command.undo())

        log_input_expected_result("Batches after undo", (undo_expected_batch_count, undo_expected_batch_numbers), (len(scene.batches), [batch.number for batch in scene.batches]))
        self.assertEqual(len(scene.batches), undo_expected_batch_count)
        self.assertSequenceEqual([batch.number for batch in scene.batches], undo_expected_batch_numbers)
        self.assertSequenceEqual([batch.size for batch in scene.batches], undo_expected_batch_sizes)

        for i in range(len(scene.batches)):
            batch = scene.batches[i]
            expected_line_number, expected_original, expected_translated = undo_expected_batch_first_lines[i]
            self.assertEqual(batch.first_line_number, expected_line_number)
            self.assertEqual(batch.originals[0].text, expected_original)
            self.assertEqual(batch.translated[0].text, expected_translated)

    def AutoSplitBatchCommandTest(self, file: Subtitles, datamodel: ProjectDataModel, test_data: dict[str, Any]) -> None:
        scene_number, batch_number = test_data['batch_number']
        min_batch_size = test_data.get('min_batch_size', 1)

        datamodel.UpdateProjectSettings({ 'min_batch_size': min_batch_size })

        scene = file.GetScene(scene_number)

        undo_expected_batch_count = len(scene.batches)
        undo_expected_batch_numbers = [batch.number for batch in scene.batches]
        undo_expected_batch_sizes = [batch.size for batch in scene.batches]
        undo_expected_line_numbers = [[line.number for line in batch.originals] for batch in scene.batches]
        undo_expected_batch_first_lines = [(batch.first_line_number, batch.originals[0].text, batch.translated[0].text) for batch in scene.batches]

        auto_split_batch_command = AutoSplitBatchCommand(scene_number, batch_number, datamodel=datamodel)
        self.assertTrue(auto_split_batch_command.execute())

        expected_batch_count = test_data['expected_batch_count']
        expected_batch_numbers = test_data['expected_batch_numbers']
        expected_batch_sizes = test_data['expected_batch_sizes']
        expected_batch_first_lines = test_data['expected_batch_first_lines']
        expected_batch_line_numbers = test_data.get('expected_batch_line_numbers', None)

        scene_batches = [batch.number for batch in scene.batches]
        batch_sizes = [batch.size for batch in scene.batches]
        batch_line_numbers = [[line.number for line in batch.originals] for batch in scene.batches]
        batch_first_lines = [(batch.first_line_number, batch.originals[0].text, batch.translated[0].text) for batch in scene.batches]

        log_input_expected_result("Split batch count", expected_batch_count, len(scene.batches))
        log_input_expected_result("Split batch numbers", expected_batch_numbers, scene_batches)
        log_input_expected_result("Split batch sizes", expected_batch_sizes, batch_sizes)
        log_input_expected_result("Split batch line numbers", expected_batch_line_numbers, batch_line_numbers)

        self.assertEqual(len(scene.batches), expected_batch_count)
        self.assertSequenceEqual(scene_batches, expected_batch_numbers)
        self.assertSequenceEqual(batch_sizes, expected_batch_sizes)
        if expected_batch_line_numbers is not None:
            self.assertSequenceEqual(batch_line_numbers, expected_batch_line_numbers)
        self.assertSequenceEqual(batch_first_lines, expected_batch_first_lines)

        self.assertTrue(auto_split_batch_command.can_undo)
        self.assertTrue(auto_split_batch_command.undo())

        undo_line_numbers = [[line.number for line in batch.originals] for batch in scene.batches]
        undo_first_lines = [(batch.first_line_number, batch.originals[0].text, batch.translated[0].text) for batch in scene.batches]

        log_input_expected_result("Batches after undo", (undo_expected_batch_count, undo_expected_batch_numbers), (len(scene.batches), [batch.number for batch in scene.batches]))
        self.assertEqual(len(scene.batches), undo_expected_batch_count)
        self.assertSequenceEqual([batch.number for batch in scene.batches], undo_expected_batch_numbers)
        self.assertSequenceEqual([batch.size for batch in scene.batches], undo_expected_batch_sizes)
        self.assertSequenceEqual(undo_line_numbers, undo_expected_line_numbers)
        self.assertSequenceEqual(undo_first_lines, undo_expected_batch_first_lines)

