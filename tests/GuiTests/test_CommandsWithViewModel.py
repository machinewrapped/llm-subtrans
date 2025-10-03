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
                datamodel, viewmodel, subtitles = self._create_gui_context(test_case['line_counts'])

                command_factory: Callable = test_case['command']
                command = command_factory(datamodel, subtitles)

                self._execute_and_update(command, datamodel, viewmodel)

                project_subtitles = self._get_project_subtitles(datamodel)
                viewmodel.assert_viewmodel_matches_subtitles(project_subtitles)
                viewmodel.assert_expected_structure(test_case['expected'])

    def _create_gui_context(self, line_counts: list[list[int]]) -> tuple[ProjectDataModel, TestableViewModel, Subtitles]:
        """ Create a ProjectDataModel, TestableViewModel, and Subtitles with well-defined structure """
        subtitles = self.create_test_subtitles(line_counts)
        datamodel = self.create_project_datamodel(subtitles)
        viewmodel = self.create_testable_viewmodel(subtitles)
        datamodel.viewmodel = viewmodel
        return datamodel, viewmodel, subtitles

    def _execute_and_update(self, command, datamodel, viewmodel) -> None:
        """
        Execute the command and apply model updates it generates to the datamodel.
        """
        success = command.execute()
        log_input_expected_result('command executed', True, success)
        self.assertTrue(success)

        log_input_expected_result('model updates generated', True, bool(command.model_updates))
        self.assertGreater(len(command.model_updates), 0)

        for model_update in command.model_updates:
            datamodel.UpdateViewModel(model_update)

        viewmodel.ProcessUpdates()

    def _get_project_subtitles(self, datamodel) -> Subtitles:
        """ 
        Retrieve the Subtitles from the ProjectDataModel, asserting they exist
        """
        self.assertIsNotNone(datamodel.project)
        assert datamodel.project is not None
        self.assertIsNotNone(datamodel.project.subtitles)
        assert datamodel.project.subtitles is not None
        return datamodel.project.subtitles

