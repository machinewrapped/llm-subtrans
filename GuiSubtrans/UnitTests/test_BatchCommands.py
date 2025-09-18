from GuiSubtrans.Commands.BatchSubtitlesCommand import BatchSubtitlesCommand

from GuiSubtrans.ProjectDataModel import ProjectDataModel
from GuiSubtrans.UnitTests.DataModelHelpers import CreateTestDataModel
from PySubtrans.Helpers.TestCases import SubtitleTestCase
from PySubtrans.Helpers.Tests import log_input_expected_result, log_test_name
from PySubtrans.Subtitles import Subtitles
from PySubtrans.UnitTests.TestData.chinese_dinner import chinese_dinner_data

class BatchCommandTests(SubtitleTestCase):
    batch_command_test_cases = [
        {
            'data': chinese_dinner_data,
            'expected_scene_count': 4,
            'expected_scene_sizes': [2, 2, 1, 1],
            'expected_scene_linecounts': [30, 25, 6, 3],
            'expected_scene_batch_sizes': [[14, 16], [12, 13], [6], [3]],
        }
    ]

    def test_BatchCommands(self):
        for test_case in self.batch_command_test_cases:
            data = test_case['data']
            log_test_name(f"Testing batch command on {data.get('movie_name')}")

            datamodel : ProjectDataModel = CreateTestDataModel(data, self.options)
            if not datamodel or not datamodel.project or not datamodel.project.subtitles:
                self.fail("Failed to create datamodel for test case")
                continue

            file : Subtitles = datamodel.project.subtitles

            with self.subTest("BatchSubtitlesCommand"):
                self.BatchSubtitlesCommandTest(file, datamodel, test_case)


    def BatchSubtitlesCommandTest(self, file : Subtitles, datamodel : ProjectDataModel, test_data : dict):
        if not datamodel.project or not datamodel.project.subtitles:
            self.fail("Failed to create datamodel for test case")
            return

        expected_scene_count = test_data['expected_scene_count']
        expected_scene_sizes = test_data['expected_scene_sizes']
        expected_scene_linecounts = test_data['expected_scene_linecounts']
        expected_scene_batch_sizes = test_data['expected_scene_batch_sizes']

        batch_command = BatchSubtitlesCommand(datamodel.project, datamodel.project_options)
        self.assertTrue(batch_command.execute())
        self.assertTrue(len(file.scenes) > 0)

        log_input_expected_result("Scene count", expected_scene_count, len(file.scenes))
        self.assertEqual(len(file.scenes), 4)

        scene_sizes = [scene.size for scene in file.scenes]
        scene_linecounts = [scene.linecount for scene in file.scenes]
        scene_batch_sizes = [[batch.size for batch in scene.batches] for scene in file.scenes]

        log_input_expected_result("Scene size", expected_scene_sizes, scene_sizes)
        log_input_expected_result("Scene line count", expected_scene_linecounts, scene_linecounts)
        log_input_expected_result("Scene batch sizes", expected_scene_batch_sizes, scene_batch_sizes)

        self.assertEqual(scene_sizes, expected_scene_sizes)
        self.assertEqual(scene_linecounts, expected_scene_linecounts)
        self.assertSequenceEqual(scene_batch_sizes, expected_scene_batch_sizes)

