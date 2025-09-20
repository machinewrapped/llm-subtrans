import os
import tempfile
import unittest
from datetime import timedelta

from PySubtrans.Helpers.TestCases import SubtitleTestCase
from PySubtrans.Helpers.Tests import log_input_expected_result, log_test_name
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleBatcher import SubtitleBatcher
from PySubtrans.SubtitleEditor import SubtitleEditor
from PySubtrans.SubtitleLine import SubtitleLine
from PySubtrans.Subtitles import Subtitles
from PySubtrans.UnitTests.TestData.chinese_dinner import chinese_dinner_data

class SubtitleEditorTests(SubtitleTestCase):
    """Test suite for SubtitleEditor class functionality"""

    def __init__(self, methodName):
        super().__init__(methodName, custom_options={
            'max_batch_size': 10,
            'min_batch_size': 1,
            'scene_threshold': 5.0,  # 5 second scene breaks for testing
        })

    def setUp(self):
        """Set up test fixtures"""
        log_test_name(self._testMethodName)

        self.temp_dir = tempfile.mkdtemp()
        self.test_srt_file = os.path.join(self.temp_dir, "test.srt")

        # Create test subtitles with some realistic timing
        self.test_lines = [
            SubtitleLine.Construct(1, timedelta(seconds=1), timedelta(seconds=3), "First line", {}),
            SubtitleLine.Construct(2, timedelta(seconds=4), timedelta(seconds=6), "Second line", {}),
            SubtitleLine.Construct(3, timedelta(seconds=7), timedelta(seconds=9), "Third line", {}),
            SubtitleLine.Construct(4, timedelta(seconds=15), timedelta(seconds=17), "Fourth line (new scene)", {}),
            SubtitleLine.Construct(5, timedelta(seconds=18), timedelta(seconds=20), "Fifth line", {}),
        ]

        # Write test SRT content
        with open(self.test_srt_file, 'w', encoding='utf-8') as f:
            original_content = chinese_dinner_data.get_str('original') or ''
            f.write(original_content)

        # Create subtitles object with test data
        self.subtitles = Subtitles(settings=SettingsType({'target_language': 'English'}))
        self.subtitles.originals = self.test_lines.copy()

    def tearDown(self):
        """Clean up test fixtures"""
        try:
            if os.path.exists(self.test_srt_file):
                os.remove(self.test_srt_file)
            os.rmdir(self.temp_dir)
        except Exception:
            pass

    def test_context_manager_functionality(self):
        """Test SubtitleEditor context manager properly acquires and releases locks"""

        editor = SubtitleEditor(self.subtitles)

        # Initially lock should not be acquired
        log_input_expected_result("initial lock acquired", False, editor._lock_acquired)
        self.assertFalse(editor._lock_acquired)

        # Test entering context
        with editor as ctx_editor:
            log_input_expected_result("context manager returns self", editor, ctx_editor)
            self.assertIs(ctx_editor, editor)

            log_input_expected_result("lock acquired in context", True, editor._lock_acquired)
            self.assertTrue(editor._lock_acquired)

        # After exiting context, lock should be released
        log_input_expected_result("lock released after context", False, editor._lock_acquired)
        self.assertFalse(editor._lock_acquired)


    def test_autobatch_functionality(self):
        """Test AutoBatch divides subtitles into scenes and batches"""

        batcher = SubtitleBatcher(self.options)

        with SubtitleEditor(self.subtitles) as editor:
            # Initially no scenes
            initial_scene_count = self.subtitles.scenecount
            log_input_expected_result("initial scene count", 0, initial_scene_count)
            self.assertEqual(initial_scene_count, 0)

            # Apply batching
            editor.AutoBatch(batcher)

            # Should have created scenes
            scene_count = self.subtitles.scenecount
            log_input_expected_result("scene count after batching > 0", True, scene_count > 0)
            self.assertGreater(scene_count, 0)

            # With our test data and 5-second threshold, should have 2 scenes
            # Lines 1-3 (gaps of 1s, 1s) and line 4-5 (gap of 8s between line 3 and 4)
            expected_scenes = 2
            log_input_expected_result("expected scene count", expected_scenes, scene_count)
            self.assertEqual(scene_count, expected_scenes)

            # Verify scene structure
            first_scene = self.subtitles.GetScene(1)
            log_input_expected_result("first scene exists", True, first_scene is not None)
            self.assertIsNotNone(first_scene)

            if first_scene:
                first_scene_batch_count = len(first_scene.batches)
                log_input_expected_result("first scene has batches", True, first_scene_batch_count > 0)
                self.assertGreater(first_scene_batch_count, 0)

    def test_add_scene(self):
        """Test AddScene adds a new scene to the subtitles"""

        from PySubtrans.SubtitleScene import SubtitleScene

        with SubtitleEditor(self.subtitles) as editor:
            initial_count = len(self.subtitles.scenes)

            # Create and add a new scene
            new_scene = SubtitleScene({'number': 99, 'summary': 'Test scene'})
            editor.AddScene(new_scene)

            new_count = len(self.subtitles.scenes)
            log_input_expected_result("scene count increased", initial_count + 1, new_count)
            self.assertEqual(new_count, initial_count + 1)

            # Verify the scene was added
            added_scene = self.subtitles.scenes[-1]
            log_input_expected_result("added scene number", 99, added_scene.number)
            self.assertEqual(added_scene.number, 99)

    def test_add_translation_via_batch(self):
        """Test adding translations through proper batch-based approach"""

        batcher = SubtitleBatcher(self.options)

        with SubtitleEditor(self.subtitles) as editor:
            editor.AutoBatch(batcher)

            # Find first batch and add a translation
            scene = self.subtitles.GetScene(1)
            if scene and scene.batches:
                batch = scene.batches[0]
                if batch.originals:
                    line_number = batch.originals[0].number
                    translation_text = "Proper batch-based translation"

                    # Add translation through batch (proper approach)
                    translated_line = SubtitleLine.Construct(
                        line_number,
                        batch.originals[0].start,
                        batch.originals[0].end,
                        translation_text,
                        {}
                    )
                    batch.AddTranslatedLine(translated_line)

                    # Verify translation was added
                    log_input_expected_result("batch has translations", True, batch.any_translated)
                    self.assertTrue(batch.any_translated)

                    # Verify we can retrieve the translation
                    retrieved_translation = batch.GetTranslatedLine(line_number)
                    log_input_expected_result("translation retrieved", True, retrieved_translation is not None)
                    self.assertIsNotNone(retrieved_translation)

                    if retrieved_translation:
                        log_input_expected_result("translation text correct", translation_text, retrieved_translation.text)
                        self.assertEqual(retrieved_translation.text, translation_text)

    def test_sanitise_removes_invalid_content(self):
        """Test Sanitise removes invalid lines, empty batches and scenes"""

        # First create some scenes with batching
        batcher = SubtitleBatcher(self.options)

        with SubtitleEditor(self.subtitles) as editor:
            editor.AutoBatch(batcher)

            # Add some invalid content to test sanitization
            scene = self.subtitles.GetScene(1)
            if scene and scene.batches:
                batch = scene.batches[0]

                # Add invalid line (no line number)
                invalid_line = SubtitleLine.Construct(0, timedelta(seconds=1), timedelta(seconds=2), "Invalid line", {})
                batch.originals.append(invalid_line)

                # Add line with missing start time
                missing_start_line = SubtitleLine.Construct(999, None, timedelta(seconds=2), "Missing start", {})
                batch.originals.append(missing_start_line)

                initial_line_count = len(batch.originals)
                log_input_expected_result("initial line count includes invalid", True, initial_line_count >= 5)
                self.assertGreaterEqual(initial_line_count, 5)  # Should have original 3 + 2 invalid = 5+

                # Apply sanitization
                editor.Sanitise()

                # Should remove invalid lines
                final_line_count = len(batch.originals)
                log_input_expected_result("final line count after sanitise", True, final_line_count < initial_line_count)
                self.assertLess(final_line_count, initial_line_count)

                # All remaining lines should be valid
                for line in batch.originals:
                    log_input_expected_result(f"line {line.number} has valid number", True, line.number and line.number > 0)
                    log_input_expected_result(f"line {line.number} has start time", True, line.start is not None)
                    self.assertTrue(line.number and line.number > 0)
                    self.assertIsNotNone(line.start)

    def test_renumber_scenes(self):
        """Test RenumberScenes ensures sequential numbering"""

        # Create scenes with batching first
        batcher = SubtitleBatcher(self.options)

        with SubtitleEditor(self.subtitles) as editor:
            editor.AutoBatch(batcher)

            # Mess up the scene numbering
            if len(self.subtitles.scenes) >= 2:
                self.subtitles.scenes[0].number = 5
                self.subtitles.scenes[1].number = 10

                # Verify numbering is messed up
                first_scene_number = self.subtitles.scenes[0].number
                second_scene_number = self.subtitles.scenes[1].number
                log_input_expected_result("first scene number before renumber", 5, first_scene_number)
                log_input_expected_result("second scene number before renumber", 10, second_scene_number)
                self.assertEqual(first_scene_number, 5)
                self.assertEqual(second_scene_number, 10)

                # Apply renumbering
                editor.RenumberScenes()

                # Should be sequential now
                renumbered_first = self.subtitles.scenes[0].number
                renumbered_second = self.subtitles.scenes[1].number
                log_input_expected_result("first scene renumbered", 1, renumbered_first)
                log_input_expected_result("second scene renumbered", 2, renumbered_second)
                self.assertEqual(renumbered_first, 1)
                self.assertEqual(renumbered_second, 2)

    def test_duplicate_originals_as_translations(self):
        """Test DuplicateOriginalsAsTranslations creates translation copies"""

        # Create scenes with batching first
        batcher = SubtitleBatcher(self.options)

        with SubtitleEditor(self.subtitles) as editor:
            editor.AutoBatch(batcher)

            # Initially should have no translations
            any_translated_before = self.subtitles.any_translated
            log_input_expected_result("no translations initially", False, any_translated_before)
            self.assertFalse(any_translated_before)

            # Duplicate originals as translations
            editor.DuplicateOriginalsAsTranslations()

            # Should now have translations
            any_translated_after = self.subtitles.any_translated
            log_input_expected_result("has translations after duplication", True, any_translated_after)
            self.assertTrue(any_translated_after)

            # Verify translations match originals
            for scene in self.subtitles.scenes:
                for batch in scene.batches:
                    if batch.originals and batch.translated:
                        log_input_expected_result(f"batch ({batch.scene},{batch.number}) original count", len(batch.originals), len(batch.translated))
                        self.assertEqual(len(batch.translated), len(batch.originals))

                        for orig, trans in zip(batch.originals, batch.translated):
                            log_input_expected_result(f"line {orig.number} number matches", orig.number, trans.number)
                            log_input_expected_result(f"line {orig.number} text matches", orig.text, trans.text)
                            self.assertEqual(trans.number, orig.number)
                            self.assertEqual(trans.text, orig.text)

    def test_duplicate_originals_fails_with_existing_translations(self):
        """Test DuplicateOriginalsAsTranslations raises error if translations exist"""

        # Create scenes with batching and add a translation
        batcher = SubtitleBatcher(self.options)

        with SubtitleEditor(self.subtitles) as editor:
            editor.AutoBatch(batcher)

            # Add a translation directly to a batch to trigger the error
            scene = self.subtitles.GetScene(1)
            if scene and scene.batches:
                batch = scene.batches[0]
                if batch.originals:
                    # Create a translated line directly in the batch
                    translated_line = SubtitleLine.Construct(
                        batch.originals[0].number,
                        batch.originals[0].start,
                        batch.originals[0].end,
                        "Direct translation",
                        {}
                    )
                    batch.translated = [translated_line]

            # Should fail because translations already exist
            from PySubtrans.SubtitleError import SubtitleError
            with self.assertRaises(SubtitleError) as context:
                editor.DuplicateOriginalsAsTranslations()

            error_message = str(context.exception)
            log_input_expected_result("error mentions existing translations", True, "already exist" in error_message.lower())
            self.assertIn("already exist", error_message.lower())

    def test_update_scene_context(self):
        """Test UpdateScene updates scene context"""

        # Create scenes with batching first
        batcher = SubtitleBatcher(self.options)

        with SubtitleEditor(self.subtitles) as editor:
            editor.AutoBatch(batcher)

            scene_number = 1
            update_data = {'summary': 'Updated scene summary', 'custom_field': 'test_value'}

            # Apply update
            result = editor.UpdateScene(scene_number, update_data)

            # Verify update was applied (result should be truthy if successful)
            log_input_expected_result("update scene returned result", True, result is not None)
            self.assertIsNotNone(result)

            # Verify scene was updated
            updated_scene = self.subtitles.GetScene(scene_number)
            if updated_scene:
                # Check if summary was updated (depending on SubtitleScene.UpdateContext implementation)
                log_input_expected_result("scene exists after update", True, updated_scene is not None)
                self.assertIsNotNone(updated_scene)

    def test_update_batch_context(self):
        """Test UpdateBatch updates batch context"""

        # Create scenes with batching first
        batcher = SubtitleBatcher(self.options)

        with SubtitleEditor(self.subtitles) as editor:
            editor.AutoBatch(batcher)

            scene_number = 1
            batch_number = 1
            update_data = {'summary': 'Updated batch summary', 'custom_field': 'test_value'}

            # Apply update
            result = editor.UpdateBatch(scene_number, batch_number, update_data)

            # Verify update was applied
            log_input_expected_result("update batch returned boolean", bool, type(result))
            self.assertIsInstance(result, bool)

            # Verify batch still exists and is accessible
            updated_batch = self.subtitles.GetBatch(scene_number, batch_number)
            log_input_expected_result("batch exists after update", True, updated_batch is not None)
            self.assertIsNotNone(updated_batch)

    def test_delete_lines(self):
        """Test DeleteLines removes lines from batches"""

        # Create scenes with batching first
        batcher = SubtitleBatcher(self.options)

        with SubtitleEditor(self.subtitles) as editor:
            editor.AutoBatch(batcher)

            # Get initial line counts
            initial_line_count = self.subtitles.linecount
            log_input_expected_result("initial line count > 0", True, initial_line_count > 0)
            self.assertGreater(initial_line_count, 0)

            # Delete some lines
            lines_to_delete = [1, 2]
            deletions = editor.DeleteLines(lines_to_delete)

            # Should return deletion info
            log_input_expected_result("deletions returned", True, len(deletions) > 0)
            self.assertGreater(len(deletions), 0)

            # Each deletion should be a tuple of (scene, batch, deleted_originals, deleted_translated)
            for deletion in deletions:
                log_input_expected_result("deletion is tuple", tuple, type(deletion))
                self.assertIsInstance(deletion, tuple)

                scene_num, batch_num, deleted_originals, deleted_translated = deletion #type: ignore
                log_input_expected_result(f"deleted originals from batch ({scene_num},{batch_num})", True, len(deleted_originals) > 0)
                self.assertGreater(len(deleted_originals), 0)

    def test_delete_lines_nonexistent(self):
        """Test DeleteLines raises error when no lines are deleted"""

        batcher = SubtitleBatcher(self.options)

        with SubtitleEditor(self.subtitles) as editor:
            editor.AutoBatch(batcher)

            # Try to delete nonexistent lines
            with self.assertRaises(ValueError) as context:
                editor.DeleteLines([999, 1000])

            error_message = str(context.exception)
            log_input_expected_result("error mentions no lines deleted", True, "no lines were deleted" in error_message.lower())
            self.assertIn("no lines were deleted", error_message.lower())

    def test_merge_scenes(self):
        """Test MergeScenes combines sequential scenes"""

        # Create subtitles with wider scene gaps to ensure multiple scenes
        wide_gap_lines = [
            SubtitleLine.Construct(1, timedelta(seconds=1), timedelta(seconds=3), "Scene 1 line 1", {}),
            SubtitleLine.Construct(2, timedelta(seconds=4), timedelta(seconds=6), "Scene 1 line 2", {}),
            SubtitleLine.Construct(3, timedelta(seconds=20), timedelta(seconds=22), "Scene 2 line 1", {}), # 14s gap
            SubtitleLine.Construct(4, timedelta(seconds=23), timedelta(seconds=25), "Scene 2 line 2", {}),
            SubtitleLine.Construct(5, timedelta(seconds=40), timedelta(seconds=42), "Scene 3 line 1", {}), # 15s gap
        ]

        self.subtitles.originals = wide_gap_lines
        batcher = SubtitleBatcher(self.options)

        with SubtitleEditor(self.subtitles) as editor:
            editor.AutoBatch(batcher)

            initial_scene_count = self.subtitles.scenecount
            log_input_expected_result("initial scene count >= 3", True, initial_scene_count >= 3)
            self.assertGreaterEqual(initial_scene_count, 3)

            # Merge first two scenes
            merged_scene = editor.MergeScenes([1, 2])

            # Should have one fewer scene
            final_scene_count = self.subtitles.scenecount
            log_input_expected_result("scene count decreased", initial_scene_count - 1, final_scene_count)
            self.assertEqual(final_scene_count, initial_scene_count - 1)

            # Merged scene should exist
            log_input_expected_result("merged scene returned", True, merged_scene is not None)
            self.assertIsNotNone(merged_scene)

            # Scenes should be renumbered sequentially
            for i, scene in enumerate(self.subtitles.scenes, 1):
                log_input_expected_result(f"scene {i} has correct number", i, scene.number)
                self.assertEqual(scene.number, i)

    def test_merge_scenes_invalid_input(self):
        """Test MergeScenes raises errors for invalid input"""

        batcher = SubtitleBatcher(self.options)

        with SubtitleEditor(self.subtitles) as editor:
            editor.AutoBatch(batcher)

            # Test empty list
            with self.assertRaises(ValueError) as context:
                editor.MergeScenes([])
            log_input_expected_result("empty list error", True, "no scene numbers" in str(context.exception).lower())
            self.assertIn("no scene numbers", str(context.exception).lower())

            # Test non-sequential scenes
            if self.subtitles.scenecount >= 3:
                with self.assertRaises(ValueError) as context:
                    editor.MergeScenes([1, 3])  # Skip scene 2
                log_input_expected_result("non-sequential error", True, "not sequential" in str(context.exception).lower())
                self.assertIn("not sequential", str(context.exception).lower())

    def test_split_scene(self):
        """Test SplitScene divides a scene at specified batch"""

        # Use wider gap lines to get scenes with multiple batches
        multi_batch_lines = [
            SubtitleLine.Construct(1, timedelta(seconds=1), timedelta(seconds=3), "Batch 1 line 1", {}),
            SubtitleLine.Construct(2, timedelta(seconds=4), timedelta(seconds=6), "Batch 1 line 2", {}),
            SubtitleLine.Construct(3, timedelta(seconds=7), timedelta(seconds=9), "Batch 1 line 3", {}),
            SubtitleLine.Construct(4, timedelta(seconds=10), timedelta(seconds=12), "Batch 2 line 1", {}),
            SubtitleLine.Construct(5, timedelta(seconds=13), timedelta(seconds=15), "Batch 2 line 2", {}),
        ]

        self.subtitles.originals = multi_batch_lines
        # Use smaller batch size to create multiple batches
        small_batch_batcher = SubtitleBatcher(SettingsType({
            'max_batch_size': 3,
            'min_batch_size': 1,
            'scene_threshold': 30.0  # Large threshold to keep in one scene
        }))

        with SubtitleEditor(self.subtitles) as editor:
            editor.AutoBatch(small_batch_batcher)

            initial_scene_count = self.subtitles.scenecount

            # Find a scene with multiple batches to split
            scene_to_split = None
            for scene in self.subtitles.scenes:
                if len(scene.batches) >= 2:
                    scene_to_split = scene
                    break

            if scene_to_split:
                initial_batch_count = len(scene_to_split.batches)
                log_input_expected_result("scene has multiple batches", True, initial_batch_count >= 2)
                self.assertGreaterEqual(initial_batch_count, 2)

                # Split at batch 2
                editor.SplitScene(scene_to_split.number, 2)

                # Should have one more scene
                final_scene_count = self.subtitles.scenecount
                log_input_expected_result("scene count increased", initial_scene_count + 1, final_scene_count)
                self.assertEqual(final_scene_count, initial_scene_count + 1)

                # All scenes should be numbered sequentially
                for i, scene in enumerate(self.subtitles.scenes, 1):
                    log_input_expected_result(f"scene {i} numbered correctly", i, scene.number)
                    self.assertEqual(scene.number, i)

    def test_merge_lines_in_batch(self):
        """Test MergeLinesInBatch combines lines within a batch"""

        batcher = SubtitleBatcher(self.options)

        with SubtitleEditor(self.subtitles) as editor:
            editor.AutoBatch(batcher)

            # Find a batch with multiple lines
            target_batch = None
            scene_num = batch_num = 0

            for scene in self.subtitles.scenes:
                for batch in scene.batches:
                    if len(batch.originals) >= 2:
                        target_batch = batch
                        scene_num = scene.number
                        batch_num = batch.number
                        break
                if target_batch:
                    break

            if target_batch:
                initial_line_count = len(target_batch.originals)
                log_input_expected_result("batch has multiple lines", True, initial_line_count >= 2)
                self.assertGreaterEqual(initial_line_count, 2)

                # Get first two line numbers
                line_numbers = [target_batch.originals[0].number, target_batch.originals[1].number]

                # Merge the lines
                merged_original, _ = editor.MergeLinesInBatch(scene_num, batch_num, line_numbers)

                # Should return merged lines
                log_input_expected_result("merged original returned", True, merged_original is not None)
                self.assertIsNotNone(merged_original)

                # Batch should have fewer lines now
                final_line_count = len(target_batch.originals)
                log_input_expected_result("line count decreased", True, final_line_count < initial_line_count)
                self.assertLess(final_line_count, initial_line_count)

    def test_context_manager_with_real_subtitles(self):
        """Test SubtitleEditor context manager with real subtitle data"""

        # Load real subtitles from file
        real_subtitles = Subtitles(self.test_srt_file)
        real_subtitles.LoadSubtitles()

        log_input_expected_result("real subtitles loaded", True, real_subtitles.has_subtitles)
        self.assertTrue(real_subtitles.has_subtitles)

        # Test context manager works with real data
        with SubtitleEditor(real_subtitles) as editor:
            log_input_expected_result("editor lock acquired", True, editor._lock_acquired)
            self.assertTrue(editor._lock_acquired)

            # Perform some operation
            batcher = SubtitleBatcher(self.options)
            editor.AutoBatch(batcher)

            # Verify operation worked
            scene_count = real_subtitles.scenecount
            log_input_expected_result("scenes created from real data", True, scene_count > 0)
            self.assertGreater(scene_count, 0)

        # Verify lock was released
        log_input_expected_result("editor lock released", False, editor._lock_acquired)
        self.assertFalse(editor._lock_acquired)


if __name__ == '__main__':
    unittest.main()
