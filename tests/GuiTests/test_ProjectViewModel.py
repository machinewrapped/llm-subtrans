from datetime import timedelta

from GuiSubtrans.GuiSubtitleTestCase import GuiSubtitleTestCase
from GuiSubtrans.ViewModel.TestableViewModel import TestableViewModel
from GuiSubtrans.ViewModel.ViewModelUpdate import ModelUpdate
from PySubtrans.Helpers.TestCases import BuildSubtitlesFromLineCounts, CreateDummyBatch, CreateDummyScene
from PySubtrans.Helpers.Tests import log_input_expected_result
from PySubtrans.SubtitleLine import SubtitleLine

class ProjectViewModelTests(GuiSubtitleTestCase):
    """
    Tests for ProjectViewModel using ModelUpdate to apply changes.

    These tests focus on verifying that the ViewModel structure and data remain consistent after updates.
    """

    def test_create_model_from_helper_subtitles(self):
        line_counts = [[3, 2], [1, 1, 2]]
        subtitles = BuildSubtitlesFromLineCounts(line_counts)

        viewmodel : TestableViewModel = self.create_testable_viewmodel(subtitles)

        # Verify the viewmodel structure matches the subtitles
        viewmodel.assert_viewmodel_matches_subtitles(subtitles)

    def test_update_scene_summary(self):
        viewmodel : TestableViewModel = self.create_testable_viewmodel_from_line_counts([[2, 2], [1, 1]])

        update = ModelUpdate()
        update.scenes.update(1, {'summary': 'Scene 1 (edited)'})
        update.ApplyToViewModel(viewmodel)

        viewmodel.assert_scene_fields([
            (1, 'summary', 'Scene 1 (edited)'),
        ])

        # Verify dataChanged was emitted for in-place update
        viewmodel.assert_signal_emitted('dataChanged', expected_count=1)

    def test_update_batch_summary(self):
        viewmodel : TestableViewModel = self.create_testable_viewmodel_from_line_counts([[2, 2], [1, 1]])

        update = ModelUpdate()
        update.batches.update((1, 1), {'summary': 'Scene 1 Batch 1 (edited)'})
        update.ApplyToViewModel(viewmodel)

        viewmodel.assert_batch_fields( [
            (1, 1, 'summary', 'Scene 1 Batch 1 (edited)'),
        ])

        # Verify dataChanged was emitted (batch setData + scene.emitDataChanged + batch.emitDataChanged = 3)
        # TODO: this count seems high, invesigate whether the explicit calls are needed
        viewmodel.assert_signal_emitted('dataChanged', expected_count=3)

    def test_update_line_text(self):
        viewmodel : TestableViewModel = self.create_testable_viewmodel_from_line_counts([[2, 2], [1, 1]])

        update = ModelUpdate()
        update.lines.update((1, 1, 1), {'text': 'Scene 1 Batch 1 Line 1 (edited)'})
        update.ApplyToViewModel(viewmodel)

        viewmodel.assert_line_contents( [
            (1, 1, 0, 1, 'Scene 1 Batch 1 Line 1 (edited)'),
        ])

        # Verify dataChanged was emitted (line item update + batch.emitDataChanged = 2)
        # TODO: this count seems high, invesigate whether the explicit calls are needed
        viewmodel.assert_signal_emitted('dataChanged', expected_count=2)

    def test_add_new_line(self):
        base_counts = [[2, 2], [1, 1]]
        subtitles = self.create_test_subtitles(base_counts)
        viewmodel : TestableViewModel = self.create_testable_viewmodel(subtitles)

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

        # Verify structure: batch (1,1) changed from 2 to 3 lines, everything else unaffected
        viewmodel.assert_expected_structure({
            'scenes': [
                {
                    'number': 1,
                    'batches': [
                        {
                            'number': 1,
                            'line_count': 3,  # Changed from 2
                            'line_texts': {next_line_number: 'Scene 1 Batch 1 Line New'}
                        },
                        {'number': 2, 'line_count': 2},
                    ]
                },
                {
                    'number': 2,
                    'batches': [
                        {'number': 1, 'line_count': 1},
                        {'number': 2, 'line_count': 1},
                    ]
                },
            ]
        })

        # Verify modelReset was emitted for structural change (adding a line)
        viewmodel.assert_signal_emitted('modelReset', expected_count=1)

    def test_remove_line(self):
        viewmodel : TestableViewModel = self.create_testable_viewmodel_from_line_counts([[2, 2], [1, 1]])

        update = ModelUpdate()
        update.lines.remove((1, 1, 2))
        update.ApplyToViewModel(viewmodel)

        # Verify structure: batch (1,1) changed from 2 to 1 line, everything else unaffected
        viewmodel.assert_expected_structure({
            'scenes': [
                {
                    'number': 1,
                    'batches': [
                        {'number': 1, 'line_count': 1},  # Changed from 2
                        {'number': 2, 'line_count': 2},
                    ]
                },
                {
                    'number': 2,
                    'batches': [
                        {'number': 1, 'line_count': 1},
                        {'number': 2, 'line_count': 1},
                    ]
                },
            ]
        })

        # Verify modelReset was emitted for structural change (removing a line)
        viewmodel.assert_signal_emitted('modelReset', expected_count=1)

    def test_add_new_batch(self):
        base_counts = [[2, 2], [1, 1]]
        subtitles = self.create_test_subtitles(base_counts)
        viewmodel : TestableViewModel = self.create_testable_viewmodel(subtitles)

        next_line_number = max(line.number for line in subtitles.originals or []) + 1
        new_batch_number = len(subtitles.GetScene(1).batches) + 1

        new_batch = CreateDummyBatch(1, new_batch_number, 2, next_line_number, timedelta(seconds=120))

        update = ModelUpdate()
        update.batches.add((1, new_batch.number), new_batch)
        update.ApplyToViewModel(viewmodel)

        # Verify structure: scene 1 changed from [2,2] to [2,2,2], scene 2 unaffected
        viewmodel.assert_expected_structure({
            'scenes': [
                {
                    'number': 1,
                    'batches': [
                        {'number': 1, 'line_count': 2},
                        {'number': 2, 'line_count': 2},
                        {'number': 3, 'line_count': 2, 'summary': new_batch.summary},  # New batch
                    ]
                },
                {
                    'number': 2,
                    'batches': [
                        {'number': 1, 'line_count': 1},
                        {'number': 2, 'line_count': 1},
                    ]
                },
            ]
        })

        # Verify modelReset was emitted for structural change (adding a batch)
        viewmodel.assert_signal_emitted('modelReset', expected_count=1)

    def test_remove_batch(self):
        base_counts = [[2, 2], [1, 1]]
        viewmodel : TestableViewModel = self.create_testable_viewmodel_from_line_counts(base_counts)

        update = ModelUpdate()
        update.batches.remove((2, 2))
        update.ApplyToViewModel(viewmodel)

        # Verify structure: scene 1 unaffected, scene 2 changed from [1,1] to [1]
        viewmodel.assert_expected_structure({
            'scenes': [
                {
                    'number': 1,
                    'batches': [
                        {'number': 1, 'line_count': 2},
                        {'number': 2, 'line_count': 2},
                    ]
                },
                {
                    'number': 2,
                    'batches': [
                        {'number': 1, 'line_count': 1},  # Batch 2 removed
                    ]
                },
            ]
        })

        # Verify modelReset was emitted for structural change (removing a batch)
        viewmodel.assert_signal_emitted('modelReset', expected_count=1)

    def test_add_new_scene(self):
        base_counts = [[2, 2], [1, 1]]
        subtitles = self.create_test_subtitles(base_counts)
        viewmodel : TestableViewModel = self.create_testable_viewmodel(subtitles)

        next_line_number = max(line.number for line in subtitles.originals or []) + 1
        new_scene_number = len(base_counts) + 1

        new_scene = CreateDummyScene(new_scene_number, [1, 1], next_line_number, timedelta(seconds=180))

        update = ModelUpdate()
        update.scenes.add(new_scene.number, new_scene)
        update.ApplyToViewModel(viewmodel)

        # Verify structure: scenes 1 and 2 unaffected, new scene 3 added with [1,1] batches
        viewmodel.assert_expected_structure({
            'scenes': [
                {
                    'number': 1,
                    'batches': [
                        {'number': 1, 'line_count': 2},
                        {'number': 2, 'line_count': 2},
                    ]
                },
                {
                    'number': 2,
                    'batches': [
                        {'number': 1, 'line_count': 1},
                        {'number': 2, 'line_count': 1},
                    ]
                },
                {
                    'number': 3,  # New scene
                    'batches': [
                        {'number': 1, 'line_count': 1},
                        {'number': 2, 'line_count': 1},
                    ]
                },
            ]
        })

        # Verify modelReset was emitted for structural change (adding a scene)
        viewmodel.assert_signal_emitted('modelReset', expected_count=1)

    
    def test_remove_scene(self):
        """Test removing a scene validates remaining scenes are correct"""
        base_counts = [[2, 2], [1, 1, 2], [3]]
        viewmodel : TestableViewModel = self.create_testable_viewmodel_from_line_counts(base_counts)

        update = ModelUpdate()
        update.scenes.remove(2)
        update.ApplyToViewModel(viewmodel)

        # Verify structure: scene 1 and 3 remain (scene numbers are stable, so 1 and 3, not 1 and 2)
        viewmodel.assert_expected_structure({
            'scenes': [
                {
                    'number': 1,
                    'summary': 'Scene 1',
                    'batches': [
                        {'number': 1, 'line_count': 2},
                        {'number': 2, 'line_count': 2},
                    ]
                },
                {
                    'number': 3,  # Original scene 3 retains its number
                    'summary': 'Scene 3',
                    'batches': [
                        {'number': 1, 'line_count': 3},
                    ]
                },
            ]
        })

        # Verify modelReset was emitted for structural change
        viewmodel.assert_signal_emitted('modelReset', expected_count=1)

    
    def test_replace_scene(self):
        """Test replacing a scene validates new structure and unaffected scenes"""
        base_counts = [[2, 2], [1, 1]]
        viewmodel : TestableViewModel = self.create_testable_viewmodel_from_line_counts(base_counts)

        # Create a new scene with different structure
        replacement_scene = CreateDummyScene(1, [3, 1], 1, timedelta(seconds=0))

        update = ModelUpdate()
        update.scenes.replace(1, replacement_scene)
        update.ApplyToViewModel(viewmodel)

        # Verify structure: scene 1 changed from [2,2] to [3,1], scene 2 unaffected [1,1]
        viewmodel.assert_expected_structure({
            'scenes': [
                {
                    'number': 1,
                    'batches': [
                        {'number': 1, 'line_count': 3},
                        {'number': 2, 'line_count': 1},
                    ]
                },
                {
                    'number': 2,
                    'batches': [
                        {'number': 1, 'line_count': 1},
                        {'number': 2, 'line_count': 1},
                    ]
                },
            ]
        })

    
    def test_replace_batch(self):
        """Test replacing a batch validates new lines and unaffected batches"""
        base_counts = [[2, 2, 3], [1, 1]]
        viewmodel : TestableViewModel = self.create_testable_viewmodel_from_line_counts(base_counts)

        # Replace batch (1,2) - was 2 lines, now 5 lines
        replacement_batch = CreateDummyBatch(1, 2, 5, 3, timedelta(seconds=10))

        update = ModelUpdate()
        update.batches.replace((1, 2), replacement_batch)
        update.ApplyToViewModel(viewmodel)

        # Verify structure: scene 1 changed from [2,2,3] to [2,5,3], scene 2 unaffected [1,1]
        viewmodel.assert_expected_structure({
            'scenes': [
                {
                    'number': 1,
                    'batches': [
                        {'number': 1, 'line_count': 2},
                        {'number': 2, 'line_count': 5},  # Changed from 2 to 5
                        {'number': 3, 'line_count': 3},
                    ]
                },
                {
                    'number': 2,
                    'batches': [
                        {'number': 1, 'line_count': 1},
                        {'number': 2, 'line_count': 1},
                    ]
                },
            ]
        })

    
    def test_delete_multiple_lines(self):
        """Test deleting multiple lines validates remaining lines and content"""
        base_counts = [[5, 4], [3, 2]]
        viewmodel : TestableViewModel = self.create_testable_viewmodel_from_line_counts(base_counts)

        update = ModelUpdate()
        update.lines.remove((1, 1, 2))
        update.lines.remove((1, 1, 4))

        update.ApplyToViewModel(viewmodel)

        # Verify structure: batch (1,1) reduced from 5 to 3 lines, with correct remaining line texts
        viewmodel.assert_expected_structure({
            'scenes': [
                {
                    'number': 1,
                    'batches': [
                        {
                            'number': 1,
                            'line_count': 3,
                            'line_texts': {  # Remaining lines 1, 3, 5 retain their original text
                                1: "Scene 1 Batch 1 Line 1",
                                3: "Scene 1 Batch 1 Line 3",
                                5: "Scene 1 Batch 1 Line 5"
                            }
                        },
                        {'number': 2, 'line_count': 4},
                    ]
                },
                {
                    'number': 2,
                    'batches': [
                        {'number': 1, 'line_count': 3},
                        {'number': 2, 'line_count': 2},
                    ]
                },
            ]
        })

        viewmodel.assert_signal_emitted('modelReset', expected_count=1)

    
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

        subtitles = BuildSubtitlesFromLineCounts(line_counts)
        viewmodel : TestableViewModel = self.create_testable_viewmodel(subtitles)

        # Verify total line count
        total_lines = sum(sum(scene) for scene in line_counts)
        actual_lines = len(subtitles.originals or [])
        log_input_expected_result("total lines", total_lines, actual_lines)
        self.assertEqual(actual_lines, total_lines)

        # Verify complete viewmodel structure matches subtitles
        viewmodel.assert_viewmodel_matches_subtitles(subtitles)

    def test_realistic_update_on_large_model(self):
        """Test performing realistic updates on a larger model"""
        line_counts = [
            [8, 10, 7],     # Scene 1: lines 1-25
            [12, 15],       # Scene 2: lines 26-52
            [9, 11, 8, 6],  # Scene 3: lines 53-86
            [14, 10],       # Scene 4: lines 87-110
        ]

        viewmodel : TestableViewModel = self.create_testable_viewmodel_from_line_counts(line_counts)

        # Get actual global line numbers from the batches
        update_line_1 = viewmodel.get_line_numbers_in_batch(1, 1)[0]
        update_line_2 = viewmodel.get_line_numbers_in_batch(3, 2)[5]
        update_line_3 = viewmodel.get_line_numbers_in_batch(4, 2)[-1]

        # Perform a complex update touching multiple scenes
        update = ModelUpdate()
        update.scenes.update(1, {'summary': 'Scene 1 - Updated'})
        update.batches.update((2, 1), {'summary': 'Scene 2 Batch 1 - Updated'})
        update.lines.update((1, 1, update_line_1), {'text': 'Updated first line'})
        update.lines.update((3, 2, update_line_2), {'text': 'Updated middle line'})
        update.lines.update((4, 2, update_line_3), {'text': 'Updated last line'})

        update.ApplyToViewModel(viewmodel)

        viewmodel.assert_scene_fields( [
            (1, 'summary', 'Scene 1 - Updated'),
            (4, 'batch_count', 2),
        ])

        viewmodel.assert_batch_fields( [
            (2, 1, 'summary', 'Scene 2 Batch 1 - Updated'),
            (4, 1, 'line_count', 14),
        ])

        viewmodel.assert_line_contents( [
            (1, 1, 0, update_line_1, 'Updated first line'),
            (3, 2, 5, update_line_2, 'Updated middle line'),
            (4, 2, -1, update_line_3, 'Updated last line'),
        ])

    def test_merge_scenes_pattern(self):
        """Test the complex update pattern used by MergeScenesCommand"""
        # Create a structure with 5 scenes
        base_counts = [[2, 2], [3], [1, 1], [2], [3, 1]]
        subtitles = self.create_test_subtitles(base_counts)
        viewmodel : TestableViewModel = self.create_testable_viewmodel(subtitles)

        # Simulate merging scenes 2 and 3 into scene 2
        # MergeScenesCommand pattern (see MergeScenesCommand.execute):
        # 1. Renumber later scenes (4→3, 5→4) to keep numbering consecutive
        # 2. Replace scene 2 with merged version (containing batches from scenes 2 and 3)
        # 3. Remove scene 3
        # Note: Scene numbers are renumbered to stay consecutive: 1,2,3,4

        # Create merged scene 2 with batches from both scenes 2 and 3: [3] + [1,1] = [3,1,1]
        merged_scene_2 = CreateDummyScene(2, [3, 1, 1], 4, timedelta(seconds=10))

        update = ModelUpdate()
        # Renumber later scenes to keep numbering consecutive (as MergeScenesCommand does)
        update.scenes.update(4, {'number': 3})
        update.scenes.update(5, {'number': 4})
        # Replace scene 2 with merged version
        update.scenes.replace(2, merged_scene_2)
        # Remove scene 3
        update.scenes.remove(3)

        update.ApplyToViewModel(viewmodel)
        viewmodel.Remap()  # Required to rebuild model dictionary after scene number changes

        # Verify structure: scenes 2 and 3 merged, later scenes renumbered
        # Original: 1:[2,2], 2:[3], 3:[1,1], 4:[2], 5:[3,1]
        # Result:   1:[2,2], 2:[3,1,1], 3:[2], 4:[3,1]  (consecutive numbering)
        viewmodel.assert_expected_structure({
            'scenes': [
                {
                    'number': 1,
                    'batches': [
                        {'number': 1, 'line_count': 2},
                        {'number': 2, 'line_count': 2},
                    ]
                },
                {
                    'number': 2,  # Merged scene 2+3
                    'batches': [
                        {'number': 1, 'line_count': 3},  # From original scene 2
                        {'number': 2, 'line_count': 1},  # From original scene 3
                        {'number': 3, 'line_count': 1},  # From original scene 3
                    ]
                },
                {
                    'number': 3,  # Was scene 4, renumbered to keep consecutive
                    'batches': [
                        {'number': 1, 'line_count': 2},
                    ]
                },
                {
                    'number': 4,  # Was scene 5, renumbered to keep consecutive
                    'batches': [
                        {'number': 1, 'line_count': 3},
                        {'number': 2, 'line_count': 1},
                    ]
                },
            ]
        })

        viewmodel.assert_signal_emitted('modelReset', expected_count=1)

    def test_merge_batches_pattern(self):
        """Test the update pattern used by MergeBatchesCommand"""
        base_counts = [[3, 4, 2, 5], [2]]
        viewmodel : TestableViewModel = self.create_testable_viewmodel_from_line_counts(base_counts)

        # Simulate merging batches 2, 3, 4 in scene 1 into batch 2
        # MergeBatchesCommand does:
        # 1. Replace batch 2 with merged batch (containing all lines from batches 2,3,4)
        # 2. Remove batches 3 and 4

        # Create merged batch with combined line count
        merged_batch = CreateDummyBatch(1, 2, 11, 4, timedelta(seconds=10))

        update = ModelUpdate()
        update.batches.replace((1, 2), merged_batch)
        update.batches.remove((1, 3))
        update.batches.remove((1, 4))

        update.ApplyToViewModel(viewmodel)

        # Verify structure: scene 1 changed from [3,4,2,5] to [3,11], scene 2 unaffected
        viewmodel.assert_expected_structure({
            'scenes': [
                {
                    'number': 1,
                    'batches': [
                        {'number': 1, 'line_count': 3},
                        {'number': 2, 'line_count': 11},  # Merged batches 2,3,4
                    ]
                },
                {
                    'number': 2,
                    'batches': [
                        {'number': 1, 'line_count': 2},
                    ]
                },
            ]
        })

        viewmodel.assert_signal_emitted('modelReset', expected_count=1)

    
    def test_split_batch_pattern(self):
        """Test the update pattern used by SplitBatchCommand"""
        base_counts = [[8, 6], [3]]
        viewmodel : TestableViewModel = self.create_testable_viewmodel_from_line_counts(base_counts)

        # Simulate splitting batch (1,1) at line 4
        # Lines 1-3 stay in batch 1, lines 4-8 move to new batch 2
        # Old batch 2 becomes batch 3
        # SplitBatchCommand would:
        # 1. Remove lines 4-8 from batch 1
        # 2. Renumber old batch 2 to batch 3
        # 3. Add new batch 2 with lines 4-8

        # Create the new batch 2 (lines 4-8)
        new_batch_2 = CreateDummyBatch(1, 2, 5, 4, timedelta(seconds=10))

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
        viewmodel.Remap()  # Required to rebuild model dictionary after batch number changes

        # Verify structure: scene 1 changed from [8,6] to [3,5,6], scene 2 unaffected
        viewmodel.assert_expected_structure({
            'scenes': [
                {
                    'number': 1,
                    'batches': [
                        {'number': 1, 'line_count': 3},  # Split from original batch 1
                        {'number': 2, 'line_count': 5},  # New batch from split
                        {'number': 3, 'line_count': 6},  # Old batch 2, renumbered
                    ]
                },
                {
                    'number': 2,
                    'batches': [
                        {'number': 1, 'line_count': 3},
                    ]
                },
            ]
        })

        viewmodel.assert_signal_emitted('modelReset', expected_count=1)

    def test_split_scene_pattern(self):
        """Test the update pattern used by SplitSceneCommand"""
        base_counts = [[4, 5, 3], [2], [6]]
        viewmodel : TestableViewModel = self.create_testable_viewmodel_from_line_counts(base_counts)

        # Simulate splitting scene 1 at batch 2
        # Batches 1 stays in scene 1, batches 2-3 move to new scene 2
        # Old scenes 2,3 become scenes 3,4
        # SplitSceneCommand would:
        # 1. Renumber old scene 2→3, scene 3→4
        # 2. Remove batches 2,3 from scene 1
        # 3. Add new scene 2 with those batches

        # Create new scene 2 with batches from old scene 1
        new_scene_2 = CreateDummyScene(2, [5, 3], 5, timedelta(seconds=10))

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
        viewmodel.Remap()  # Required to rebuild model dictionary after scene number changes

        # Verify structure: [4,5,3], [2], [6] → [4], [5,3], [2], [6]
        viewmodel.assert_expected_structure({
            'scenes': [
                {
                    'number': 1,
                    'batches': [
                        {'number': 1, 'line_count': 4},  # Original batch 1
                    ]
                },
                {
                    'number': 2,
                    'batches': [
                        {'number': 1, 'line_count': 5},  # From old scene 1 batch 2
                        {'number': 2, 'line_count': 3},  # From old scene 1 batch 3
                    ]
                },
                {
                    'number': 3,
                    'batches': [
                        {'number': 1, 'line_count': 2},  # Old scene 2, renumbered
                    ]
                },
                {
                    'number': 4,
                    'batches': [
                        {'number': 1, 'line_count': 6},  # Old scene 3, renumbered
                    ]
                },
            ]
        })

        viewmodel.assert_signal_emitted('modelReset', expected_count=1)

    def test_multiple_updates_in_sequence(self):
        """Test applying multiple updates sequentially"""
        # Structure: [[3, 3], [2, 2]] = lines 1-3, 4-6, 7-8, 9-10
        base_counts = [[3, 3], [2, 2]]
        viewmodel : TestableViewModel = self.create_testable_viewmodel_from_line_counts(base_counts)

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

        # Verify structure unchanged [[3, 3], [2, 2]] and all updates applied correctly
        # Validate all line texts to ensure no unintended changes
        viewmodel.assert_expected_structure({
            'scenes': [
                {
                    'number': 1,
                    'summary': 'First update',
                    'batches': [
                        {
                            'number': 1,
                            'line_count': 3,
                            'summary': 'Second update',
                            'line_texts': {
                                1: 'Third update',  # Updated
                                2: 'Scene 1 Batch 1 Line 2',  # Unchanged
                                3: 'Scene 1 Batch 1 Line 3',  # Unchanged
                            }
                        },
                        {'number': 2, 'line_count': 3},
                    ]
                },
                {
                    'number': 2,
                    'batches': [
                        {
                            'number': 1,
                            'line_count': 2,
                            'line_texts': {7: 'Scene 2 Batch 1 Line 1'}  # Spot-check
                        },
                        {'number': 2, 'line_count': 2},
                    ]
                },
            ]
        })

        # Verify signals: scene(1) + batch(3) + line(2) = 6
        viewmodel.assert_signal_emitted('dataChanged', expected_count=6)

    def test_complex_multi_operation_update(self):
        """Test a complex update with multiple operations at once"""
        # Scene 1: [3, 3, 3] = lines 1-3, 4-6, 7-9
        # Scene 2: [2, 2] = lines 10-11, 12-13
        # Scene 3: [4] = lines 14-17
        base_counts = [[3, 3, 3], [2, 2], [4]]
        viewmodel : TestableViewModel = self.create_testable_viewmodel_from_line_counts(base_counts)

        # Perform multiple updates in one ModelUpdate (scene, batch, and line updates)
        update = ModelUpdate()
        update.scenes.update(1, {'summary': 'Updated scene 1'})
        update.batches.update((1, 2), {'summary': 'Updated batch 1,2'})
        update.lines.update((1, 1, 1), {'text': 'Updated line text'})
        update.lines.update((3, 1, 15), {'text': 'Another updated line'})

        update.ApplyToViewModel(viewmodel)

        # Verify structure unchanged [[3, 3, 3], [2, 2], [4]] and all updates applied correctly
        # Validate line texts to ensure no unintended changes
        viewmodel.assert_expected_structure({
            'scenes': [
                {
                    'number': 1,
                    'summary': 'Updated scene 1',
                    'batches': [
                        {
                            'number': 1,
                            'line_count': 3,
                            'line_texts': {
                                1: 'Updated line text',  # Updated
                                2: 'Scene 1 Batch 1 Line 2',  # Unchanged
                            }
                        },
                        {
                            'number': 2,
                            'line_count': 3,
                            'summary': 'Updated batch 1,2'
                        },
                        {'number': 3, 'line_count': 3},
                    ]
                },
                {
                    'number': 2,
                    'batches': [
                        {
                            'number': 1,
                            'line_count': 2,
                            'line_texts': {10: 'Scene 2 Batch 1 Line 1'}  # Spot-check
                        },
                        {'number': 2, 'line_count': 2},
                    ]
                },
                {
                    'number': 3,
                    'batches': [
                        {
                            'number': 1,
                            'line_count': 4,
                            'line_texts': {
                                14: 'Scene 3 Batch 1 Line 1',  # Unchanged
                                15: 'Another updated line',  # Updated
                                16: 'Scene 3 Batch 1 Line 3',  # Unchanged
                            }
                        },
                    ]
                },
            ]
        })
