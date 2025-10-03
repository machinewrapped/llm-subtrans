import unittest
from datetime import timedelta
from typing import cast

from GuiSubtrans.GuiSubtitleTestCase import GuiSubtitleTestCase
from GuiSubtrans.ViewModel.BatchItem import BatchItem
from GuiSubtrans.ViewModel.LineItem import LineItem
from GuiSubtrans.ViewModel.SceneItem import SceneItem
from GuiSubtrans.ViewModel.TestableViewModel import TestableViewModel
from GuiSubtrans.ViewModel.ViewModel import ProjectViewModel
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

        # Get actual global line number
        global_line_1 = viewmodel.get_line_numbers_in_batch(1, 1)[0]

        update = ModelUpdate()
        update.lines.update((1, 1, global_line_1), {'text': 'Scene 1 Batch 1 Line 1 (edited)'})
        update.ApplyToViewModel(viewmodel)

        viewmodel.assert_line_texts( [
            (1, 1, 0, global_line_1, 'Scene 1 Batch 1 Line 1 (edited)'),
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

        # Verify batch line count increased
        viewmodel.assert_batch_fields([
            (1, 1, 'line_count', 3),
        ])

        # Verify new line was added with correct text
        batch_one_item = viewmodel.test_get_batch_item(1, 1)
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
        viewmodel.assert_signal_emitted('modelReset', expected_count=1)

    def test_remove_line(self):
        viewmodel : TestableViewModel = self.create_testable_viewmodel_from_line_counts([[2, 2], [1, 1]])

        update = ModelUpdate()
        update.lines.remove((1, 1, 2))
        update.ApplyToViewModel(viewmodel)

        viewmodel.assert_batch_fields( [
            (1, 1, 'line_count', 1),
        ])

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

        # Verify scene batch count increased
        expected_batch_count = len(base_counts[0]) + 1
        viewmodel.assert_scene_fields([
            (1, 'batch_count', expected_batch_count),
        ])

        # Verify new batch was added with correct summary
        viewmodel.assert_batch_fields([
            (1, new_batch_number, 'summary', new_batch.summary),
        ])

        # Verify modelReset was emitted for structural change (adding a batch)
        viewmodel.assert_signal_emitted('modelReset', expected_count=1)

    def test_remove_batch(self):
        base_counts = [[2, 2], [1, 1]]
        viewmodel : TestableViewModel = self.create_testable_viewmodel_from_line_counts(base_counts)

        update = ModelUpdate()
        update.batches.remove((2, 2))
        update.ApplyToViewModel(viewmodel)

        expected_batch_count = len(base_counts[1]) - 1
        viewmodel.assert_scene_fields( [
            (2, 'batch_count', expected_batch_count),
        ])

        # Verify modelReset was emitted for structural change (removing a batch)
        viewmodel.assert_signal_emitted('modelReset', expected_count=1)

    def test_add_new_scene(self):
        base_counts = [[2, 2], [1, 1]]
        subtitles = self.create_test_subtitles(base_counts)
        viewmodel : TestableViewModel = self.create_testable_viewmodel(subtitles)

        initial_scene_count = viewmodel.rowCount()
        log_input_expected_result("initial scene count", len(base_counts), initial_scene_count)
        self.assertEqual(initial_scene_count, len(base_counts))

        next_line_number = max(line.number for line in subtitles.originals or []) + 1
        new_scene_number = initial_scene_count + 1

        new_scene = CreateDummyScene(new_scene_number, [1, 1], next_line_number, timedelta(seconds=180))

        update = ModelUpdate()
        update.scenes.add(new_scene.number, new_scene)
        update.ApplyToViewModel(viewmodel)

        # Verify scene count increased
        root_item = viewmodel.getRootItem()
        final_scene_count = root_item.rowCount()
        log_input_expected_result("final scene count", initial_scene_count + 1, final_scene_count)
        self.assertEqual(final_scene_count, initial_scene_count + 1)

        # Verify new scene was added with correct structure
        viewmodel.assert_scene_fields([
            (3, 'number', 3),
            (3, 'batch_count', 2),
        ])

        # Verify modelReset was emitted for structural change (adding a scene)
        viewmodel.assert_signal_emitted('modelReset', expected_count=1)

    
    def test_remove_scene(self):
        """Test removing a scene validates remaining scenes are correct"""
        base_counts = [[2, 2], [1, 1, 2], [3]]
        viewmodel : TestableViewModel = self.create_testable_viewmodel_from_line_counts(base_counts)

        # Remove scene 2 (which has 3 batches)
        update = ModelUpdate()
        update.scenes.remove(2)
        update.ApplyToViewModel(viewmodel)

        root_item = viewmodel.getRootItem()
        final_scene_count = root_item.rowCount()
        log_input_expected_result("final scene count", len(base_counts) - 1, final_scene_count)
        self.assertEqual(final_scene_count, len(base_counts) - 1)

        # Verify scene 1 is still intact with correct structure
        viewmodel.assert_scene_fields( [
            (1, 'summary', 'Scene 1'),
            (1, 'batch_count', 2),
        ])

        # Check scene 1 batches have correct line counts
        viewmodel.assert_batch_fields( [
            (1, 1, 'line_count', 2),
            (1, 2, 'line_count', 2),
        ])

        # Verify scene 3 retains its original number (scene numbers are stable identifiers)
        # After removing scene 2, we should have 2 scenes total: scene 1 and scene 3
        viewmodel.assert_scene_fields( [
            (3, 'summary', 'Scene 3'),
            (3, 'batch_count', 1),
        ])

        viewmodel.assert_batch_fields( [
            (3, 1, 'line_count', 3),
        ])

        # Verify modelReset was emitted for structural change
        viewmodel.assert_signal_emitted('modelReset', expected_count=1)

    
    def test_replace_scene(self):
        """Test replacing a scene validates new structure and unaffected scenes"""
        base_counts = [[2, 2], [1, 1]]
        viewmodel : TestableViewModel = self.create_testable_viewmodel_from_line_counts(base_counts)

        # Create a new scene with different structure - was [2,2], now [3,1]
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

        # Delete lines 2 and 4 from batch (1,1), leaving lines 1, 3, 5
        update = ModelUpdate()
        update.lines.remove((1, 1, 2))
        update.lines.remove((1, 1, 4))

        update.ApplyToViewModel(viewmodel)

        # Verify overall structure: batch (1,1) reduced from 5 to 3 lines, others unaffected
        viewmodel.assert_expected_structure({
            'scenes': [
                {
                    'number': 1,
                    'batches': [
                        {'number': 1, 'line_count': 3},  # Changed from 5
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

        # Verify remaining lines have correct text (originally lines 1, 3, 5, now at positions 1, 2, 3)
        line_at_pos_1 = viewmodel.test_get_line_item(1, 1, 1)
        log_input_expected_result("line at position 1 text", "Scene 1 Batch 1 Line 1", line_at_pos_1.line_text)
        self.assertEqual(line_at_pos_1.line_text, "Scene 1 Batch 1 Line 1")

        line_at_pos_2 = viewmodel.test_get_line_item(1, 1, 2)
        log_input_expected_result("line at position 2 text", "Scene 1 Batch 1 Line 3", line_at_pos_2.line_text)
        self.assertEqual(line_at_pos_2.line_text, "Scene 1 Batch 1 Line 3")

        line_at_pos_3 = viewmodel.test_get_line_item(1, 1, 3)
        log_input_expected_result("line at position 3 text", "Scene 1 Batch 1 Line 5", line_at_pos_3.line_text)
        self.assertEqual(line_at_pos_3.line_text, "Scene 1 Batch 1 Line 5")

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
        # Use a moderately large structure
        line_counts = [
            [8, 10, 7],     # Scene 1: lines 1-25
            [12, 15],       # Scene 2: lines 26-52
            [9, 11, 8, 6],  # Scene 3: lines 53-86
            [14, 10],       # Scene 4: lines 87-110
        ]

        viewmodel : TestableViewModel = self.create_testable_viewmodel_from_line_counts(line_counts)

        # Get actual global line numbers from the batches
        global_line_1 = viewmodel.get_line_numbers_in_batch(1, 1)[0]
        global_line_67 = viewmodel.get_line_numbers_in_batch(3, 2)[5]
        global_line_110 = viewmodel.get_line_numbers_in_batch(4, 2)[-1]

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

        # Verify updates and unaffected structure
        viewmodel.assert_scene_fields( [
            (1, 'summary', 'Scene 1 - Updated'),
            (4, 'batch_count', 2),
        ])

        viewmodel.assert_batch_fields( [
            (2, 1, 'summary', 'Scene 2 Batch 1 - Updated'),
            (4, 1, 'line_count', 14),
        ])

        viewmodel.assert_line_texts( [
            (1, 1, 0, global_line_1, 'Updated first line'),
            (3, 2, 5, global_line_67, 'Updated middle line'),
            (4, 2, -1, global_line_110, 'Updated last line'),
        ])

    @unittest.skip("Test needs to be rewritten to properly simulate MergeScenesCommand")
    def test_merge_scenes_pattern(self):
        """Test the complex update pattern used by MergeScenesCommand"""
        # Create a structure with 5 scenes to make renumbering interesting
        base_counts = [[2, 2], [3], [1, 1], [2], [3, 1]]
        subtitles = self.create_test_subtitles(base_counts)
        viewmodel : TestableViewModel = self.create_testable_viewmodel(subtitles)

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
        scene_1 = viewmodel.test_get_scene_item(1)
        log_input_expected_result("scene 1 batch count", 2, scene_1.batch_count)
        self.assertEqual(scene_1.batch_count, 2)

        # Verify scene 2 is the merged scene (now has 3 batches: 3+1+1 from original scenes 2+3)
        scene_2 = viewmodel.test_get_scene_item(2)
        log_input_expected_result("scene 2 batch count", 3, scene_2.batch_count)
        self.assertEqual(scene_2.batch_count, 3)

        batch_2_1 = viewmodel.test_get_batch_item(2, 1)
        log_input_expected_result("batch (2,1) line count", 3, batch_2_1.line_count)
        self.assertEqual(batch_2_1.line_count, 3)

        # Verify scene 3 no longer exists (was removed)
        # But scene 4 (originally scene 4) should now be scene 3
        scene_3 = viewmodel.test_get_scene_item(3)
        log_input_expected_result("scene 3 (was scene 4) batch count", 1, scene_3.batch_count)
        self.assertEqual(scene_3.batch_count, 1)

        batch_3_1 = viewmodel.test_get_batch_item(3, 1)
        log_input_expected_result("batch (3,1) line count", 2, batch_3_1.line_count)
        self.assertEqual(batch_3_1.line_count, 2)

        # Verify scene 4 (originally scene 5) structure
        scene_4 = viewmodel.test_get_scene_item(4)
        log_input_expected_result("scene 4 (was scene 5) batch count", 2, scene_4.batch_count)
        self.assertEqual(scene_4.batch_count, 2)

        viewmodel.assert_signal_emitted('modelReset', expected_count=1)

    def test_merge_batches_pattern(self):
        """Test the update pattern used by MergeBatchesCommand"""
        # Create a scene with multiple batches to merge
        base_counts = [[3, 4, 2, 5], [2]]
        viewmodel : TestableViewModel = self.create_testable_viewmodel_from_line_counts(base_counts)

        # Simulate merging batches 2, 3, 4 in scene 1 into batch 2
        # MergeBatchesCommand does:
        # 1. Replace batch 2 with merged batch (containing all lines from batches 2,3,4)
        # 2. Remove batches 3 and 4

        # Create merged batch with combined line count (4+2+5=11 lines)
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
        # Create a scene with a large batch to split
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
        # Create scenes where we'll split scene 1
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
        base_counts = [[3, 3], [2, 2]]
        viewmodel : TestableViewModel = self.create_testable_viewmodel_from_line_counts(base_counts)

        # Get actual global line number
        global_line_1 = viewmodel.get_line_numbers_in_batch(1, 1)[0]

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
        update3.lines.update((1, 1, global_line_1), {'text': 'Third update'})
        update3.ApplyToViewModel(viewmodel)

        # Verify all updates were applied
        viewmodel.assert_scene_fields( [
            (1, 'summary', 'First update'),
        ])

        viewmodel.assert_batch_fields( [
            (1, 1, 'summary', 'Second update'),
        ])

        viewmodel.assert_line_texts( [
            (1, 1, 0, global_line_1, 'Third update'),
        ])

        # Verify signals: scene(1) + batch(3) + line(2) = 6
        viewmodel.assert_signal_emitted('dataChanged', expected_count=6)

    def test_complex_multi_operation_update(self):
        """Test a complex update with multiple operations at once"""
        # Scene 1: [3, 3, 3] = lines 1-9
        # Scene 2: [2, 2] = lines 10-13
        # Scene 3: [4] = lines 14-17
        base_counts = [[3, 3, 3], [2, 2], [4]]
        viewmodel : TestableViewModel = self.create_testable_viewmodel_from_line_counts(base_counts)

        # Get actual global line numbers
        global_line_1 = viewmodel.get_line_numbers_in_batch(1, 1)[0]
        global_line_15 = viewmodel.get_line_numbers_in_batch(3, 1)[1]

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

        # Verify updates
        viewmodel.assert_scene_fields( [
            (1, 'summary', 'Updated scene 1'),
        ])

        viewmodel.assert_batch_fields( [
            (1, 2, 'summary', 'Updated batch 1,2'),
        ])

        viewmodel.assert_line_texts( [
            (1, 1, 0, global_line_1, 'Updated line text'),
            (3, 1, 1, global_line_15, 'Another updated line'),
        ])
