from collections.abc import Callable

from GuiSubtrans.Commands.AutoSplitBatchCommand import AutoSplitBatchCommand
from GuiSubtrans.Commands.DeleteLinesCommand import DeleteLinesCommand
from GuiSubtrans.Commands.EditBatchCommand import EditBatchCommand
from GuiSubtrans.Commands.EditLineCommand import EditLineCommand
from GuiSubtrans.Commands.EditSceneCommand import EditSceneCommand
from GuiSubtrans.Commands.MergeBatchesCommand import MergeBatchesCommand
from GuiSubtrans.Commands.MergeLinesCommand import MergeLinesCommand
from GuiSubtrans.Commands.MergeScenesCommand import MergeScenesCommand
from GuiSubtrans.Commands.SplitBatchCommand import SplitBatchCommand
from GuiSubtrans.Commands.SplitSceneCommand import SplitSceneCommand
from GuiSubtrans.GuiSubtitleTestCase import GuiSubtitleTestCase
from GuiSubtrans.ProjectDataModel import ProjectDataModel
from GuiSubtrans.ViewModel.TestableViewModel import TestableViewModel
from PySubtrans.Helpers.Tests import log_input_expected_result
from PySubtrans.Subtitles import Subtitles


class CommandsWithViewModelTests(GuiSubtitleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.options.update({
            'min_batch_size': 1,
            'max_batch_size': 6
        })

    def test_CommandsWithViewModel(self) -> None:
        test_cases = [
            {
                'description': 'EditSceneCommand updates scene summary',
                'line_counts': [[2, 2]],
                'command': lambda datamodel, _: EditSceneCommand(1, {'summary': 'Updated Scene Summary'}, datamodel),
                'expected': {
                    'scenes': [
                        {
                            'number': 1,
                            'summary': 'Updated Scene Summary',
                            'batches': [
                                {'number': 1, 'line_numbers': [1, 2]},
                                {'number': 2, 'line_numbers': [3, 4]}
                            ]
                        }
                    ]
                }
            },
            {
                'description': 'EditBatchCommand updates batch summary',
                'line_counts': [[2, 2]],
                'command': lambda datamodel, _: EditBatchCommand(1, 2, {'summary': 'Edited Batch'}, datamodel),
                'expected': {
                    'scenes': [
                        {
                            'number': 1,
                            'summary': 'Scene 1',
                            'batches': [
                                {'number': 1, 'line_numbers': [1, 2], 'summary': 'Scene 1 Batch 1'},
                                {'number': 2, 'line_numbers': [3, 4], 'summary': 'Edited Batch'}
                            ]
                        }
                    ]
                }
            },
            {
                'description': 'EditLineCommand updates line text',
                'line_counts': [[2, 2]],
                'command': lambda datamodel, _: EditLineCommand(2, {'text': 'Edited line text'}, datamodel),
                'expected': {
                    'scenes': [
                        {
                            'number': 1,
                            'summary': 'Scene 1',
                            'batches': [
                                {
                                    'number': 1,
                                    'line_numbers': [1, 2],
                                    'line_texts': {2: 'Edited line text'}
                                },
                                {'number': 2, 'line_numbers': [3, 4]}
                            ]
                        }
                    ]
                }
            },
            {
                'description': 'DeleteLinesCommand removes the specified lines',
                'line_counts': [[2, 2]],
                'command': lambda datamodel, _: DeleteLinesCommand([2, 3], datamodel),
                'expected': {
                    'scenes': [
                        {
                            'number': 1,
                            'summary': 'Scene 1',
                            'batches': [
                                {'number': 1, 'line_numbers': [1]},
                                {'number': 2, 'line_numbers': [4]}
                            ]
                        }
                    ]
                }
            },
            {
                'description': 'MergeLinesCommand combines sequential lines',
                'line_counts': [[3, 1]],
                'command': lambda datamodel, _: MergeLinesCommand([1, 2], datamodel),
                'expected': {
                    'scenes': [
                        {
                            'number': 1,
                            'summary': 'Scene 1',
                            'batches': [
                                {
                                    'number': 1,
                                    'line_numbers': [1, 3],
                                    'line_texts': {1: 'Scene 1 Batch 1 Line 1\nScene 1 Batch 1 Line 2'}
                                },
                                {'number': 2, 'line_numbers': [4]}
                            ]
                        }
                    ]
                }
            },
            {
                'description': 'MergeBatchesCommand merges adjacent batches',
                'line_counts': [[1, 1, 1]],
                'command': lambda datamodel, _: MergeBatchesCommand(1, [1, 2], datamodel),
                'expected': {
                    'scenes': [
                        {
                            'number': 1,
                            'summary': 'Scene 1',
                            'batches': [
                                {'number': 1, 'line_numbers': [1, 2], 'summary': 'Scene 1 Batch 1\nScene 1 Batch 2'},
                                {'number': 2, 'line_numbers': [3], 'summary': 'Scene 1 Batch 3'}
                            ]
                        }
                    ]
                }
            },
            {
                'description': 'MergeScenesCommand combines consecutive scenes',
                'line_counts': [[1, 1], [1], [1]],
                'command': lambda datamodel, _: MergeScenesCommand([1, 2], datamodel),
                'expected': {
                    'scenes': [
                        {
                            'number': 1,
                            'summary': 'Scene 1\nScene 2',
                            'batches': [
                                {'number': 1, 'line_numbers': [1]},
                                {'number': 2, 'line_numbers': [2]},
                                {'number': 3, 'line_numbers': [3]}
                            ]
                        },
                        {
                            'number': 2,
                            'summary': 'Scene 3',
                            'batches': [
                                {'number': 1, 'line_numbers': [4]}
                            ]
                        }
                    ]
                }
            },
            {
                'description': 'SplitBatchCommand creates a new batch from split line',
                'line_counts': [[4]],
                'command': lambda datamodel, _: SplitBatchCommand(1, 1, 3, datamodel=datamodel),
                'expected': {
                    'scenes': [
                        {
                            'number': 1,
                            'summary': 'Scene 1',
                            'batches': [
                                {'number': 1, 'line_numbers': [1, 2]},
                                {'number': 2, 'line_numbers': [3, 4]}
                            ]
                        }
                    ]
                }
            },
            {
                'description': 'AutoSplitBatchCommand automatically splits a batch',
                'line_counts': [[6]],
                'command': lambda datamodel, _: AutoSplitBatchCommand(1, 1, datamodel=datamodel),
                'expected': {
                    'scenes': [
                        {
                            'number': 1,
                            'summary': 'Scene 1',
                            'batches': [
                                {'number': 1, 'line_numbers': [1, 2, 3]},
                                {'number': 2, 'line_numbers': [4, 5, 6]}
                            ]
                        }
                    ]
                }
            },
            {
                'description': 'SplitSceneCommand moves later batches to new scene',
                'line_counts': [[1, 1, 1]],
                'command': lambda datamodel, _: SplitSceneCommand(1, 2, datamodel),
                'expected': {
                    'scenes': [
                        {
                            'number': 1,
                            'summary': 'Scene 1',
                            'batches': [
                                {'number': 1, 'line_numbers': [1]}
                            ]
                        },
                        {
                            'number': 2,
                            'batches': [
                                {'number': 1, 'line_numbers': [2]},
                                {'number': 2, 'line_numbers': [3]}
                            ]
                        }
                    ]
                }
            }
        ]

        for test_case in test_cases:
            with self.subTest(test_case['description']):
                datamodel, viewmodel, subtitles = self._create_context(test_case['line_counts'])
                command_factory: Callable = test_case['command']
                command = command_factory(datamodel, subtitles)

                self._execute_and_update(command, datamodel, viewmodel)

                project_subtitles = self._get_project_subtitles(datamodel)
                self._assert_viewmodel_matches_subtitles(viewmodel, project_subtitles)
                self._assert_expected_structure(viewmodel, test_case['expected'])

    def _create_context(self, line_counts: list[list[int]]) -> tuple[ProjectDataModel, TestableViewModel, Subtitles]:
        viewmodel = TestableViewModel(self)
        subtitles = viewmodel.CreateSubtitles(line_counts)
        datamodel = self.create_project_datamodel(subtitles)
        datamodel.viewmodel = viewmodel
        return datamodel, viewmodel, subtitles

    def _execute_and_update(self, command, datamodel, viewmodel) -> None:
        success = command.execute()
        log_input_expected_result('command executed', True, success)
        self.assertTrue(success)

        log_input_expected_result('model updates generated', True, bool(command.model_updates))
        self.assertGreater(len(command.model_updates), 0)

        for model_update in command.model_updates:
            datamodel.UpdateViewModel(model_update)

        viewmodel.ProcessUpdates()

    def _get_project_subtitles(self, datamodel) -> Subtitles:
        self.assertIsNotNone(datamodel.project)
        assert datamodel.project is not None
        self.assertIsNotNone(datamodel.project.subtitles)
        assert datamodel.project.subtitles is not None
        return datamodel.project.subtitles

    def _assert_viewmodel_matches_subtitles(self, viewmodel: TestableViewModel, subtitles: Subtitles) -> None:
        expected_scene_numbers = [scene.number for scene in subtitles.scenes]
        actual_scene_numbers = sorted(viewmodel.model.keys())
        log_input_expected_result('scene numbers match project', expected_scene_numbers, actual_scene_numbers)
        self.assertSequenceEqual(actual_scene_numbers, expected_scene_numbers)

        for scene in subtitles.scenes:
            scene_item = viewmodel.test_get_scene_item(scene.number)
            log_input_expected_result(f'scene {scene.number} summary', scene.summary, scene_item.summary)
            self.assertEqual(scene_item.summary, scene.summary)

            expected_batch_numbers = [batch.number for batch in scene.batches]
            actual_batch_numbers = sorted(scene_item.batches.keys())
            log_input_expected_result(f'scene {scene.number} batch numbers', expected_batch_numbers, actual_batch_numbers)
            self.assertSequenceEqual(actual_batch_numbers, expected_batch_numbers)

            for batch in scene.batches:
                batch_item = viewmodel.test_get_batch_item(scene.number, batch.number)
                log_input_expected_result(f'batch ({scene.number},{batch.number}) summary', batch.summary, batch_item.summary)
                self.assertEqual(batch_item.summary, batch.summary)

                expected_line_numbers = [line.number for line in batch.originals]
                actual_line_numbers = viewmodel.get_line_numbers_in_batch(scene.number, batch.number)
                log_input_expected_result(f'batch ({scene.number},{batch.number}) line numbers', expected_line_numbers, actual_line_numbers)
                self.assertSequenceEqual(actual_line_numbers, expected_line_numbers)

                for line in batch.originals:
                    line_item = batch_item.lines.get(line.number)
                    log_input_expected_result(f'line ({scene.number},{batch.number},{line.number}) exists', True, line_item is not None)
                    self.assertIsNotNone(line_item)
                    if line_item:
                        log_input_expected_result(f'line ({scene.number},{batch.number},{line.number}) text', line.text, line_item.line_text)
                        self.assertEqual(line_item.line_text, line.text)

    def _assert_expected_structure(self, viewmodel: TestableViewModel, expected: dict) -> None:
        expected_scenes = expected.get('scenes', [])
        expected_scene_numbers = [scene_data['number'] for scene_data in expected_scenes]
        actual_scene_numbers = sorted(viewmodel.model.keys())
        log_input_expected_result('expected scene numbers', expected_scene_numbers, actual_scene_numbers)
        self.assertSequenceEqual(actual_scene_numbers, expected_scene_numbers)

        for scene_data in expected_scenes:
            scene_number = scene_data['number']
            scene_item = viewmodel.test_get_scene_item(scene_number)

            if 'summary' in scene_data:
                expected_summary = scene_data['summary']
                log_input_expected_result(f'scene {scene_number} expected summary', expected_summary, scene_item.summary)
                self.assertEqual(scene_item.summary, expected_summary)

            expected_batches = scene_data.get('batches', [])
            expected_batch_numbers = [batch_data['number'] for batch_data in expected_batches]
            actual_batch_numbers = sorted(scene_item.batches.keys())
            log_input_expected_result(f'scene {scene_number} expected batches', expected_batch_numbers, actual_batch_numbers)
            self.assertSequenceEqual(actual_batch_numbers, expected_batch_numbers)

            for batch_data in expected_batches:
                batch_number = batch_data['number']
                batch_item = viewmodel.test_get_batch_item(scene_number, batch_number)

                if 'summary' in batch_data:
                    expected_batch_summary = batch_data['summary']
                    log_input_expected_result(f'batch ({scene_number},{batch_number}) expected summary', expected_batch_summary, batch_item.summary)
                    self.assertEqual(batch_item.summary, expected_batch_summary)

                expected_line_numbers = batch_data.get('line_numbers')
                if expected_line_numbers is not None:
                    actual_line_numbers = viewmodel.get_line_numbers_in_batch(scene_number, batch_number)
                    log_input_expected_result(f'batch ({scene_number},{batch_number}) expected line numbers', expected_line_numbers, actual_line_numbers)
                    self.assertSequenceEqual(actual_line_numbers, expected_line_numbers)

                expected_line_texts = batch_data.get('line_texts', {})
                for line_number, expected_text in expected_line_texts.items():
                    line_item = batch_item.lines.get(line_number)
                    log_input_expected_result(f'line ({scene_number},{batch_number},{line_number}) expected text', expected_text, line_item.line_text if line_item else None)
                    self.assertIsNotNone(line_item)
                    if line_item:
                        self.assertEqual(line_item.line_text, expected_text)
