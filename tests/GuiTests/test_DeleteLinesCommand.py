from copy import deepcopy

from GuiSubtrans.Commands.DeleteLinesCommand import DeleteLinesCommand
from GuiSubtrans.ProjectDataModel import ProjectDataModel
from .DataModelHelpers import CreateTestDataModelBatched
from PySubtrans.Helpers.TestCases import SubtitleTestCase
from PySubtrans.Helpers.Tests import log_info, log_input_expected_result, log_test_name
from PySubtrans.Subtitles import Subtitles
from ..TestData.chinese_dinner import chinese_dinner_data

class DeleteLinesCommandTest(SubtitleTestCase):
    delete_lines_test_cases = [
        {
            'batch_number': (1,1),
            'lines_to_delete': [1,2,3],
            'expected_batch_size': 11,
            'expected_line_numbers': [4,5,6,7,8,9,10,11,12,13,14]
        },
        {
            'batch_number': (1,1),
            'lines_to_delete': [9,10],
            'expected_batch_size': 12,
            'expected_line_numbers': [1,2,3,4,5,6,7,8,11,12,13,14]
        },
        {
            'batch_number': (1,1),
            'lines_to_delete': [14],
            'expected_batch_size': 13,
            'expected_line_numbers': [1,2,3,4,5,6,7,8,9,10,11,12,13]
        },
        {
            'batch_number': (1,2),
            'lines_to_delete': [15],
            'expected_batch_size': 15,
            'expected_line_numbers': [16,17,18,19,20,21,22,23,24,25,26,27,28,29,30]
        },
        {
            'batch_number': (2,1),
            'lines_to_delete': [33,34,35,36,37,38,39,40,41,42],
            'expected_batch_size': 2,
            'expected_line_numbers': [31,32]
        }
    ]


    def test_DeleteLinesCommand(self):

        data = deepcopy(chinese_dinner_data)

        datamodel : ProjectDataModel = CreateTestDataModelBatched(data, options=self.options)
        if not datamodel.project or not datamodel.project.subtitles:
            self.fail("Failed to create test datamodel with subtitles")
            return

        subtitles: Subtitles = datamodel.project.subtitles

        for test_case in self.delete_lines_test_cases:
            scene_number, batch_number = test_case['batch_number']
            lines_to_delete = test_case['lines_to_delete']

            expected_batch_size = test_case['expected_batch_size']
            expected_line_numbers = test_case['expected_line_numbers']

            batch = subtitles.GetBatch(scene_number, batch_number)

            initial_batch_size = len(batch.originals)
            initial_line_numbers = [line.number for line in batch.originals]
            initial_line_contents = [line.text for line in batch.originals]
            initial_translated_contents = [line.text for line in batch.translated]

            log_info(f"Deleting lines {lines_to_delete} from batch {scene_number}.{batch_number}")

            self.assertTrue(all([any([line.number == line_number for line in batch.originals]) for line_number in lines_to_delete]))

            command = DeleteLinesCommand(lines_to_delete, datamodel=datamodel)
            self.assertTrue(command.execute())

            log_input_expected_result("After Delete", expected_batch_size, len(batch.originals))
            self.assertEqual(len(batch.originals), expected_batch_size)
            self.assertSequenceEqual([line.number for line in batch.originals], expected_line_numbers)

            self.assertTrue(command.can_undo)
            self.assertTrue(command.undo())

            log_input_expected_result("After Undo", initial_batch_size, len(batch.originals))
            self.assertEqual(len(batch.originals), initial_batch_size)
            self.assertSequenceEqual([line.number for line in batch.originals], initial_line_numbers)
            self.assertSequenceEqual([line.text for line in batch.originals], initial_line_contents)
            self.assertSequenceEqual([line.text for line in batch.translated], initial_translated_contents)


