from __future__ import annotations
from typing import Any

from GuiSubtrans.Command import Command
from GuiSubtrans.Commands.EditBatchCommand import EditBatchCommand
from GuiSubtrans.Commands.EditLineCommand import EditLineCommand
from GuiSubtrans.Commands.EditSceneCommand import EditSceneCommand
from GuiSubtrans.ProjectDataModel import ProjectDataModel

from GuiSubtrans.UnitTests.DataModelHelpers import CreateTestDataModelBatched
from PySubtrans.Helpers.TestCases import SubtitleTestCase
from PySubtrans.Helpers.Tests import log_input_expected_result, log_test_name
from PySubtrans.Subtitles import Subtitles
from PySubtrans.UnitTests.TestData.chinese_dinner import chinese_dinner_data

class EditCommandsTests(SubtitleTestCase):
    command_test_cases = [
        {
            'data': chinese_dinner_data,
            'tests' : [
                {
                    'test': 'EditSceneCommandTest',
                    'scene_number': 2,
                    'edit': {
                        'summary': "This is an edited scene summary.",
                    },
                    'expected_summary': "This is an edited scene summary.",
                },
                {
                    'test': 'EditBatchCommandTest',
                    'batch_number': (2, 1),
                    'edit': {
                        'summary': "This is an edited batch summary.",
                    },
                    'expected_summary': "This is an edited batch summary.",
                },
                {
                    'test': 'EditLineCommandTest',
                    'line_number': 10,
                    'edit': {
                        'text': "This is an edited original line.",
                        'translation': "This is an edited translated line.",
                    },
                    'expected_scene_number': 1,
                    'expected_batch_number': 1,
                    'expect_translated_line': True,
                    'expected_original': "This is an edited original line.",
                    'expected_translation': "This is an edited translated line.",
                }
            ]
        }
    ]

    def test_Commands(self):
        for test_case in self.command_test_cases:
            data = test_case['data']
            log_test_name(f"Testing edit commands on {data.get('movie_name')}")

            datamodel = CreateTestDataModelBatched(data, options=self.options)
            self.assertIsNotNone(datamodel)
            self.assertIsNotNone(datamodel.project)
            assert datamodel.project is not None  # Type narrowing for PyLance
            self.assertIsNotNone(datamodel.project.subtitles)
            
            subtitles: Subtitles = datamodel.project.subtitles
            undo_stack: list[Command] = []

            for command_data in test_case['tests']:
                test = command_data['test']
                command: Command | None = None

                with self.subTest(test):
                    log_test_name(f"{test} test")
                    if test == 'EditSceneCommandTest':
                        command = self.EditSceneCommandTest(subtitles, datamodel, command_data)
                    elif test == 'EditBatchCommandTest':
                        command = self.EditBatchCommandTest(subtitles, datamodel, command_data)
                    elif test == 'EditLineCommandTest':
                        command = self.EditLineCommandTest(subtitles, datamodel, command_data)
                    else:
                        self.fail(f"Unknown test type: {test}")

                    self.assertIsNotNone(command, f"Command should not be None for test {test}")
                    assert command is not None  # Type narrowing for PyLance
                    self.assertTrue(command.can_undo)
                    undo_stack.append(command)

            for command in reversed(undo_stack):
                self.assertTrue(command.can_undo)
                self.assertTrue(command.undo())

            reference_datamodel = CreateTestDataModelBatched(data, options=self.options)
            self.assertIsNotNone(reference_datamodel)
            self.assertIsNotNone(reference_datamodel.project)
            assert reference_datamodel.project is not None  # Type narrowing for PyLance
            self.assertIsNotNone(reference_datamodel.project.subtitles)
            
            reference_subtitles = reference_datamodel.project.subtitles
            self._assert_same_as_reference(subtitles, reference_subtitles)

    def EditSceneCommandTest(self, subtitles: Subtitles, datamodel: ProjectDataModel, test_data: dict[str, Any]) -> Command:
        scene_number: int = test_data['scene_number']

        scene = subtitles.GetScene(scene_number)
        self.assertIsNotNone(scene, f"Scene {scene_number} should exist")
        assert scene is not None  # Type narrowing for PyLance

        original_scene_number = scene.number
        original_size = scene.size
        original_linecount = scene.linecount
        original_summary = scene.summary

        edit = test_data['edit']

        edit_scene_command = EditSceneCommand(scene_number, edit=edit, datamodel=datamodel)
        self.assertTrue(edit_scene_command.execute())

        expected_number = test_data.get('expected_number', original_scene_number)
        expected_summary = test_data.get('expected_summary', original_summary)
        expected_size = test_data.get('expected_size', original_size)
        expected_linecount = test_data.get('expected_linecount', original_linecount)

        expected = (expected_number, expected_size, expected_linecount, expected_summary)
        actual = (scene.number, scene.size, scene.linecount, scene.summary)
        log_input_expected_result("Edit Scene", expected, actual)

        self.assertEqual(scene.number, expected_number)
        self.assertEqual(scene.size, expected_size)
        self.assertEqual(scene.linecount, expected_linecount)
        self.assertEqual(scene.summary, expected_summary)

        return edit_scene_command

    def EditBatchCommandTest(self, subtitles: Subtitles, datamodel: ProjectDataModel, test_data: dict[str, Any]) -> Command:
        scene_number, batch_number = test_data['batch_number']

        scene = subtitles.GetScene(scene_number)
        self.assertIsNotNone(scene, f"Scene {scene_number} should exist")
        assert scene is not None  # Type narrowing for PyLance

        batch = scene.GetBatch(batch_number)
        self.assertIsNotNone(batch, f"Batch {batch_number} in scene {scene_number} should exist")
        assert batch is not None  # Type narrowing for PyLance

        original_scene_number = scene.number
        original_batch_number = batch.number
        original_size = batch.size
        original_summary = batch.summary

        edit = test_data['edit']

        edit_batch_command = EditBatchCommand(scene_number, batch_number, edit=edit, datamodel=datamodel)
        self.assertTrue(edit_batch_command.execute())

        expected_scene_number = test_data.get('expected_scene_number', original_scene_number)
        expected_batch_number = test_data.get('expected_batch_number', original_batch_number)
        expected_size = test_data.get('expected_size', original_size)
        expected_summary = test_data.get('expected_summary', original_summary)

        log_input_expected_result("Edit Batch", 
                                 (expected_scene_number, expected_batch_number, expected_size, expected_summary), 
                                 (scene.number, batch.number, batch.size, batch.summary))

        self.assertEqual(scene.number, expected_scene_number)
        self.assertEqual(batch.number, expected_batch_number)
        self.assertEqual(batch.size, expected_size)
        self.assertEqual(batch.summary, expected_summary)

        return edit_batch_command

    def EditLineCommandTest(self, subtitles: Subtitles, datamodel: ProjectDataModel, test_data: dict[str, Any]) -> Command:
        line_number: int = test_data['line_number']

        batch = subtitles.GetBatchContainingLine(line_number)
        self.assertIsNotNone(batch, f"Batch containing line {line_number} should exist")
        assert batch is not None  # Type narrowing for PyLance

        line = batch.GetOriginalLine(line_number)
        self.assertIsNotNone(line, f"Original line {line_number} should exist")
        assert line is not None  # Type narrowing for PyLance
        self.assertEqual(line.number, line_number)

        original_line_number = line.number
        original_text = line.text
        original_translation = line.translation

        edit = test_data['edit']

        edit_line_command = EditLineCommand(line_number, edit=edit, datamodel=datamodel)
        self.assertTrue(edit_line_command.execute())

        expected_line_number = test_data.get('expected_line_number', original_line_number)
        expected_original = test_data.get('expected_original', original_text)
        expected_translation = test_data.get('expected_translation', original_translation)

        log_input_expected_result("Edit Line", 
                                 (expected_line_number, expected_original, expected_translation), 
                                 (line.number, line.text, line.translation))

        edited_line = batch.GetOriginalLine(line_number)
        self.assertIsNotNone(edited_line, f"Edited line {line_number} should exist")
        assert edited_line is not None  # Type narrowing for PyLance

        self.assertEqual(edited_line.number, expected_line_number)
        self.assertEqual(edited_line.text, expected_original)
        self.assertEqual(edited_line.translation, expected_translation)

        translated_line = batch.GetTranslatedLine(line_number)
        expect_translated_line: bool = test_data.get('expect_translated_line', False)

        if expect_translated_line:
            self.assertIsNotNone(translated_line, f"Translated line {line_number} should exist when expected")
            assert translated_line is not None  # Type narrowing for PyLance
            self.assertEqual(translated_line.number, expected_line_number)
            self.assertEqual(translated_line.text, expected_translation)
            self.assertEqual(translated_line.original, expected_original)
        else:
            self.assertIsNone(translated_line, f"Translated line {line_number} should not exist when not expected")

        return edit_line_command
