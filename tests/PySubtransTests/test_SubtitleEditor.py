import os
import tempfile
import unittest
from datetime import timedelta

from PySubtrans.Helpers.TestCases import BuildSubtitlesFromLineCounts, SubtitleTestCase
from PySubtrans.Helpers.Tests import (
    skip_if_debugger_attached,
)
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleBatcher import SubtitleBatcher
from PySubtrans.SubtitleEditor import SubtitleEditor
from PySubtrans.SubtitleLine import SubtitleLine
from PySubtrans.Subtitles import Subtitles
from ..TestData.chinese_dinner import chinese_dinner_data

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
        super().setUp()

        self.temp_dir = tempfile.mkdtemp()
        self.test_srt_file = os.path.join(self.temp_dir, "test.srt")

        self.line_structure = [[4, 3], [3, 3], [4]]
        self.test_lines = BuildSubtitlesFromLineCounts(self.line_structure).originals or []

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
        self.assertLoggedFalse("initial lock acquired", editor._lock_acquired)

        # Test entering context
        with editor as ctx_editor:
            self.assertLoggedIs("context manager returns self", editor, ctx_editor)

            self.assertLoggedTrue("lock acquired in context", editor._lock_acquired)

        # After exiting context, lock should be released
        self.assertLoggedFalse("lock released after context", editor._lock_acquired)

    def test_exit_callback_invoked_on_success(self):
        """Test that exit callback is invoked with success flag when no exception occurs"""

        callback_results: list[bool] = []
        editor = SubtitleEditor(self.subtitles, lambda success: callback_results.append(success))

        with editor:
            pass

        self.assertLoggedEqual("callback invoked count", 1, len(callback_results))
        self.assertLoggedTrue("callback success flag", callback_results[0])

    @skip_if_debugger_attached
    def test_exit_callback_invoked_on_failure(self):
        """Test that exit callback receives failure flag when an exception occurs"""
        callback_results: list[bool] = []

        with self.assertRaises(ValueError):
            with SubtitleEditor(self.subtitles, lambda success: callback_results.append(success)):
                raise ValueError("Test exception for callback")

        self.assertLoggedEqual("callback invoked on failure", 1, len(callback_results))
        self.assertLoggedFalse("callback failure flag", callback_results[0])

    @skip_if_debugger_attached
    def test_exit_callback_exception_propagates(self):
        """Exit callback exceptions should propagate out of the context manager"""
        def failing_callback(_: bool) -> None:
            raise RuntimeError("Callback failure")

        editor = SubtitleEditor(self.subtitles, failing_callback)

        with self.assertRaises(RuntimeError):
            with editor:
                pass

        self.assertLoggedFalse("lock released after callback failure", editor._lock_acquired)


    def test_autobatch_functionality(self):
        """Test AutoBatch divides subtitles into scenes and batches"""

        batcher = SubtitleBatcher(self.options)

        with SubtitleEditor(self.subtitles) as editor:
            # Initially no scenes
            initial_scene_count = self.subtitles.scenecount
            self.assertLoggedEqual("initial scene count", 0, initial_scene_count)

            # Apply batching
            editor.AutoBatch(batcher)

            # Should have created scenes
            scene_count = self.subtitles.scenecount
            self.assertLoggedGreater("scene count after batching > 0", scene_count, 0)

            # With our structured test data and 5-second threshold, helper creates three scenes
            expected_scenes = len(self.line_structure)
            self.assertLoggedEqual("expected scene count", expected_scenes, scene_count)

            # Verify scene structure
            first_scene = self.subtitles.GetScene(1)
            self.assertLoggedIsNotNone("first scene exists", first_scene)

            if first_scene:
                first_scene_batch_count = len(first_scene.batches)
                self.assertLoggedGreater("first scene has batches", first_scene_batch_count, 0)

    def test_add_scene(self):
        """Test AddScene adds a new scene to the subtitles"""

        from PySubtrans.SubtitleScene import SubtitleScene

        with SubtitleEditor(self.subtitles) as editor:
            initial_count = len(self.subtitles.scenes)

            # Create and add a new scene
            new_scene = SubtitleScene({'number': 99, 'summary': 'Test scene'})
            editor.AddScene(new_scene)

            new_count = len(self.subtitles.scenes)
            self.assertLoggedEqual("scene count increased", initial_count + 1, new_count)

            # Verify the scene was added
            added_scene = self.subtitles.scenes[-1]
            self.assertLoggedEqual("added scene number", 99, added_scene.number)

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
                    self.assertLoggedTrue("batch has translations", batch.any_translated)

                    # Verify we can retrieve the translation
                    retrieved_translation = batch.GetTranslatedLine(line_number)
                    self.assertLoggedIsNotNone("translation retrieved", retrieved_translation)

                    if retrieved_translation:
                        self.assertLoggedEqual(
                            "translation text correct",
                            translation_text,
                            retrieved_translation.text,
                        )

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
                self.assertLoggedGreaterEqual(
                    "initial line count includes invalid",
                    initial_line_count,
                    5,
                )  # Should have original 3 + 2 invalid = 5+

                # Apply sanitization
                editor.Sanitise()

                # Should remove invalid lines
                final_line_count = len(batch.originals)
                self.assertLoggedLess(
                    "final line count after sanitise",
                    final_line_count,
                    initial_line_count,
                )

                # All remaining lines should be valid
                for line in batch.originals:
                    self.assertLoggedTrue(
                        f"line {line.number} has valid number",
                        bool(line.number and line.number > 0),
                        input_value=line.number,
                    )
                    self.assertLoggedIsNotNone(
                        f"line {line.number} has start time",
                        line.start,
                    )

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
                self.assertLoggedEqual("first scene number before renumber", 5, first_scene_number)
                self.assertLoggedEqual("second scene number before renumber", 10, second_scene_number)

                # Apply renumbering
                editor.RenumberScenes()

                # Should be sequential now
                renumbered_first = self.subtitles.scenes[0].number
                renumbered_second = self.subtitles.scenes[1].number
                self.assertLoggedEqual("first scene renumbered", 1, renumbered_first)
                self.assertLoggedEqual("second scene renumbered", 2, renumbered_second)

    def test_duplicate_originals_as_translations(self):
        """Test DuplicateOriginalsAsTranslations creates translation copies"""

        # Create scenes with batching first
        batcher = SubtitleBatcher(self.options)

        with SubtitleEditor(self.subtitles) as editor:
            editor.AutoBatch(batcher)

            # Initially should have no translations
            any_translated_before = self.subtitles.any_translated
            self.assertLoggedFalse("no translations initially", any_translated_before)

            # Duplicate originals as translations
            editor.DuplicateOriginalsAsTranslations()

            # Should now have translations
            any_translated_after = self.subtitles.any_translated
            self.assertLoggedTrue("has translations after duplication", any_translated_after)

            # Verify translations match originals
            for scene in self.subtitles.scenes:
                for batch in scene.batches:
                    if batch.originals and batch.translated:
                        self.assertLoggedEqual(
                            f"batch ({batch.scene},{batch.number}) original count",
                            len(batch.originals),
                            len(batch.translated),
                        )

                        for orig, trans in zip(batch.originals, batch.translated):
                            self.assertLoggedEqual(
                                f"line {orig.number} number matches",
                                orig.number,
                                trans.number,
                            )
                            self.assertLoggedEqual(
                                f"line {orig.number} text matches",
                                orig.text,
                                trans.text,
                            )

    @skip_if_debugger_attached
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
            self.assertLoggedTrue(
                "error mentions existing translations",
                "already exist" in error_message.lower(),
                input_value=error_message,
            )

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
            self.assertLoggedIsNotNone("update scene returned result", result)

            # Verify scene was updated
            updated_scene = self.subtitles.GetScene(scene_number)
            if updated_scene:
                # Check if summary was updated (depending on SubtitleScene.UpdateContext implementation)
                self.assertLoggedIsNotNone("scene exists after update", updated_scene)

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
            self.assertLoggedEqual("update batch returned boolean", bool, type(result))

            # Verify batch still exists and is accessible
            updated_batch = self.subtitles.GetBatch(scene_number, batch_number)
            self.assertLoggedIsNotNone("batch exists after update", updated_batch)

    def test_delete_lines(self):
        """Test DeleteLines removes lines from batches"""

        # Create scenes with batching first
        batcher = SubtitleBatcher(self.options)

        with SubtitleEditor(self.subtitles) as editor:
            editor.AutoBatch(batcher)

            # Get initial line counts
            initial_line_count = self.subtitles.linecount
            self.assertLoggedGreater("initial line count > 0", initial_line_count, 0)

            # Delete some lines
            lines_to_delete = [1, 2]
            deletions = editor.DeleteLines(lines_to_delete)

            # Should return deletion info
            self.assertLoggedGreater("deletions returned", len(deletions), 0)

            # Each deletion should be a tuple of (scene, batch, deleted_originals, deleted_translated)
            for deletion in deletions:
                self.assertLoggedEqual("deletion is tuple", tuple, type(deletion))

                scene_num, batch_num, deleted_originals, deleted_translated = deletion #type: ignore
                self.assertLoggedGreater(
                    f"deleted originals from batch ({scene_num},{batch_num})",
                    len(deleted_originals),
                    0,
                )

    @skip_if_debugger_attached
    def test_delete_lines_nonexistent(self):
        """Test DeleteLines raises error when no lines are deleted"""
        batcher = SubtitleBatcher(self.options)

        with SubtitleEditor(self.subtitles) as editor:
            editor.AutoBatch(batcher)

            # Try to delete nonexistent lines
            with self.assertRaises(ValueError) as context:
                editor.DeleteLines([999, 1000])

            error_message = str(context.exception)
            self.assertLoggedTrue(
                "error mentions no lines deleted",
                "no lines were deleted" in error_message.lower(),
                input_value=error_message,
            )

    def test_merge_scenes(self):
        """Test MergeScenes combines sequential scenes"""

        merge_structure = BuildSubtitlesFromLineCounts([[2], [2], [1]])
        wide_gap_lines = merge_structure.originals or []

        self.subtitles.originals = wide_gap_lines
        batcher = SubtitleBatcher(self.options)

        with SubtitleEditor(self.subtitles) as editor:
            editor.AutoBatch(batcher)

            initial_scene_count = self.subtitles.scenecount
            self.assertLoggedGreaterEqual("initial scene count >= 3", initial_scene_count, 3)

            # Merge first two scenes
            merged_scene = editor.MergeScenes([1, 2])

            # Should have one fewer scene
            final_scene_count = self.subtitles.scenecount
            self.assertLoggedEqual("scene count decreased", initial_scene_count - 1, final_scene_count)

            # Merged scene should exist
            self.assertLoggedIsNotNone("merged scene returned", merged_scene)

            # Scenes should be renumbered sequentially
            for i, scene in enumerate(self.subtitles.scenes, 1):
                self.assertLoggedEqual(f"scene {i} has correct number", i, scene.number)

    @skip_if_debugger_attached
    def test_merge_scenes_invalid_input(self):
        """Test MergeScenes raises errors for invalid input"""
        batcher = SubtitleBatcher(self.options)

        with SubtitleEditor(self.subtitles) as editor:
            editor.AutoBatch(batcher)

            # Test empty list
            with self.assertRaises(ValueError) as context:
                editor.MergeScenes([])
            self.assertLoggedTrue(
                "empty list error",
                "no scene numbers" in str(context.exception).lower(),
                input_value=str(context.exception),
            )

            # Test non-sequential scenes
            if self.subtitles.scenecount >= 3:
                with self.assertRaises(ValueError) as context:
                    editor.MergeScenes([1, 3])  # Skip scene 2
                self.assertLoggedTrue(
                    "non-sequential error",
                    "not sequential" in str(context.exception).lower(),
                    input_value=str(context.exception),
                )

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
                self.assertLoggedGreaterEqual("scene has multiple batches", initial_batch_count, 2)

                # Split at batch 2
                editor.SplitScene(scene_to_split.number, 2)

                # Should have one more scene
                final_scene_count = self.subtitles.scenecount
                self.assertLoggedEqual("scene count increased", initial_scene_count + 1, final_scene_count)

                # All scenes should be numbered sequentially
                for i, scene in enumerate(self.subtitles.scenes, 1):
                    self.assertLoggedEqual(f"scene {i} numbered correctly", i, scene.number)

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
                self.assertLoggedGreaterEqual("batch has multiple lines", initial_line_count, 2)

                # Get first two line numbers
                line_numbers = [target_batch.originals[0].number, target_batch.originals[1].number]

                # Merge the lines
                merged_original, _ = editor.MergeLinesInBatch(scene_num, batch_num, line_numbers)

                # Should return merged lines
                self.assertLoggedIsNotNone("merged original returned", merged_original)

                # Batch should have fewer lines now
                final_line_count = len(target_batch.originals)
                self.assertLoggedLess("line count decreased", final_line_count, initial_line_count)

    def test_context_manager_with_real_subtitles(self):
        """Test SubtitleEditor context manager with real subtitle data"""

        # Load real subtitles from file
        real_subtitles = Subtitles(self.test_srt_file)
        real_subtitles.LoadSubtitles()

        self.assertLoggedTrue("real subtitles loaded", real_subtitles.has_subtitles)

        # Test context manager works with real data
        with SubtitleEditor(real_subtitles) as editor:
            self.assertLoggedTrue("editor lock acquired", editor._lock_acquired)

            # Perform some operation
            batcher = SubtitleBatcher(self.options)
            editor.AutoBatch(batcher)

            # Verify operation worked
            scene_count = real_subtitles.scenecount
            self.assertLoggedGreater("scenes created from real data", scene_count, 0)

        # Verify lock was released
        self.assertLoggedFalse("editor lock released", editor._lock_acquired)

    def test_update_line_text(self):
        """Test UpdateLine updates line text"""

        batcher = SubtitleBatcher(self.options)

        with SubtitleEditor(self.subtitles) as editor:
            editor.AutoBatch(batcher)

            # Find a line to update
            test_line_number = 1
            batch = self.subtitles.GetBatchContainingLine(test_line_number)
            self.assertIsNotNone(batch)
            assert batch is not None

            original_line = batch.GetOriginalLine(test_line_number)
            self.assertIsNotNone(original_line)
            assert original_line is not None

            new_text = "Updated text content"

            # Update the line text
            result = editor.UpdateLine(test_line_number, {'text': new_text})

            self.assertLoggedTrue("update line returned True", result)

            # Verify text was updated
            updated_line = batch.GetOriginalLine(test_line_number)
            assert updated_line is not None
            self.assertLoggedEqual("line text updated", new_text, updated_line.text)

    def test_update_line_translation_new(self):
        """Test UpdateLine creates new translation when none exists"""

        batcher = SubtitleBatcher(self.options)

        with SubtitleEditor(self.subtitles) as editor:
            editor.AutoBatch(batcher)

            test_line_number = 2
            batch = self.subtitles.GetBatchContainingLine(test_line_number)
            self.assertIsNotNone(batch)
            assert batch is not None

            # Verify no translation exists initially
            translated_line = batch.GetTranslatedLine(test_line_number)
            self.assertLoggedIsNone("no initial translation", translated_line)

            new_translation = "New translation text"

            # Update with translation
            result = editor.UpdateLine(test_line_number, {'translation': new_translation})

            self.assertLoggedTrue("update line returned True", result)

            # Verify translation was created
            translated_line = batch.GetTranslatedLine(test_line_number)
            self.assertLoggedIsNotNone("translation created", translated_line)

            if translated_line:
                self.assertLoggedEqual("translation text correct", new_translation, translated_line.text)

                # Verify original line also has translation reference
                original_line = batch.GetOriginalLine(test_line_number)
                assert original_line is not None
                self.assertLoggedEqual("original line translation", new_translation, original_line.translation)

    def test_update_line_translation_existing(self):
        """Test UpdateLine updates existing translation"""

        batcher = SubtitleBatcher(self.options)

        with SubtitleEditor(self.subtitles) as editor:
            editor.AutoBatch(batcher)

            test_line_number = 3
            batch = self.subtitles.GetBatchContainingLine(test_line_number)
            self.assertIsNotNone(batch)
            assert batch is not None

            # Create initial translation
            initial_translation = "Initial translation"
            editor.UpdateLine(test_line_number, {'translation': initial_translation})

            # Verify translation exists
            translated_line = batch.GetTranslatedLine(test_line_number)
            self.assertIsNotNone(translated_line)
            if translated_line:
                self.assertEqual(translated_line.text, initial_translation)

            # Update existing translation
            new_translation = "Updated translation text"
            result = editor.UpdateLine(test_line_number, {'translation': new_translation})

            self.assertLoggedTrue("update existing translation returned True", result)

            # Verify translation was updated
            updated_translated_line = batch.GetTranslatedLine(test_line_number)
            assert updated_translated_line is not None
            self.assertLoggedEqual("translation updated", new_translation, updated_translated_line.text)

    def test_update_line_timing(self):
        """Test UpdateLine updates start and end times"""

        batcher = SubtitleBatcher(self.options)

        with SubtitleEditor(self.subtitles) as editor:
            editor.AutoBatch(batcher)

            test_line_number = 4
            batch = self.subtitles.GetBatchContainingLine(test_line_number)
            self.assertIsNotNone(batch)
            assert batch is not None

            original_line = batch.GetOriginalLine(test_line_number)
            self.assertIsNotNone(original_line)
            assert original_line is not None

            new_start = timedelta(seconds=10)
            new_end = timedelta(seconds=15)

            # Update timing
            result = editor.UpdateLine(test_line_number, {
                'start': new_start,
                'end': new_end
            })

            self.assertLoggedTrue("update timing returned True", result)

            # Verify timing was updated
            updated_line = batch.GetOriginalLine(test_line_number)
            assert updated_line is not None
            self.assertLoggedEqual("start time updated", new_start, updated_line.start)
            self.assertLoggedEqual("end time updated", new_end, updated_line.end)
            self.assertEqual(updated_line.start, new_start)
            self.assertEqual(updated_line.end, new_end)

    def test_update_line_timing_with_translation_sync(self):
        """Test UpdateLine syncs timing changes to translated lines"""

        batcher = SubtitleBatcher(self.options)

        with SubtitleEditor(self.subtitles) as editor:
            editor.AutoBatch(batcher)

            test_line_number = 5
            batch = self.subtitles.GetBatchContainingLine(test_line_number)
            self.assertIsNotNone(batch)
            assert batch is not None

            # Create translation first
            editor.UpdateLine(test_line_number, {'translation': "Test translation"})

            translated_line = batch.GetTranslatedLine(test_line_number)
            self.assertIsNotNone(translated_line)

            new_start = timedelta(seconds=20)
            new_end = timedelta(seconds=25)

            # Update timing and translation
            result = editor.UpdateLine(test_line_number, {
                'start': new_start,
                'end': new_end,
                'translation': "Updated translation"
            })

            self.assertLoggedTrue("update with sync returned True", result)

            # Verify translated line timing was synced
            updated_translated_line = batch.GetTranslatedLine(test_line_number)
            assert updated_translated_line is not None
            self.assertLoggedEqual("translated start synced", new_start, updated_translated_line.start)
            self.assertLoggedEqual("translated end synced", new_end, updated_translated_line.end)
            self.assertEqual(updated_translated_line.start, new_start)
            self.assertEqual(updated_translated_line.end, new_end)

    def test_update_line_metadata(self):
        """Test UpdateLine updates line metadata"""

        batcher = SubtitleBatcher(self.options)

        with SubtitleEditor(self.subtitles) as editor:
            editor.AutoBatch(batcher)

            test_line_number = 1
            batch = self.subtitles.GetBatchContainingLine(test_line_number)
            self.assertIsNotNone(batch)
            assert batch is not None

            original_line = batch.GetOriginalLine(test_line_number)
            self.assertIsNotNone(original_line)
            assert original_line is not None

            new_metadata = {'speaker': 'John', 'emotion': 'angry', 'volume': 'loud'}

            # Update metadata
            result = editor.UpdateLine(test_line_number, {'metadata': new_metadata})

            self.assertLoggedTrue("update metadata returned True", result)

            # Verify metadata was updated
            updated_line = batch.GetOriginalLine(test_line_number)
            assert updated_line is not None
            self.assertLoggedEqual("metadata updated", new_metadata, updated_line.metadata)
            self.assertEqual(updated_line.metadata, new_metadata)

    def test_update_line_multiple_fields(self):
        """Test UpdateLine updates multiple fields at once"""

        batcher = SubtitleBatcher(self.options)

        with SubtitleEditor(self.subtitles) as editor:
            editor.AutoBatch(batcher)

            test_line_number = 2
            batch = self.subtitles.GetBatchContainingLine(test_line_number)
            self.assertIsNotNone(batch)
            assert batch is not None

            new_text = "Multi-field update text"
            new_translation = "Multi-field translation"
            new_start = timedelta(seconds=30)
            new_end = timedelta(seconds=35)
            new_metadata = {'test': 'multi-field'}

            # Update multiple fields
            result = editor.UpdateLine(test_line_number, {
                'text': new_text,
                'translation': new_translation,
                'start': new_start,
                'end': new_end,
                'metadata': new_metadata
            })

            self.assertLoggedTrue("multi-field update returned True", result)

            # Verify all fields were updated
            updated_line = batch.GetOriginalLine(test_line_number)
            assert updated_line is not None
            self.assertLoggedEqual("text updated", new_text, updated_line.text)
            self.assertLoggedEqual("translation updated", new_translation, updated_line.translation)
            self.assertLoggedEqual("start updated", new_start, updated_line.start)
            self.assertLoggedEqual("end updated", new_end, updated_line.end)
            self.assertLoggedEqual("metadata updated", new_metadata, updated_line.metadata)

            self.assertEqual(updated_line.text, new_text)
            self.assertEqual(updated_line.translation, new_translation)
            self.assertEqual(updated_line.start, new_start)
            self.assertEqual(updated_line.end, new_end)
            self.assertEqual(updated_line.metadata, new_metadata)

            # Verify translated line was created and synced
            translated_line = batch.GetTranslatedLine(test_line_number)
            self.assertIsNotNone(translated_line)
            if translated_line:
                self.assertEqual(translated_line.text, new_translation)
                self.assertEqual(translated_line.start, new_start)
                self.assertEqual(translated_line.end, new_end)
                self.assertEqual(translated_line.metadata, new_metadata)

    def test_update_line_no_change(self):
        """Test UpdateLine returns False when no changes are made"""

        batcher = SubtitleBatcher(self.options)

        with SubtitleEditor(self.subtitles) as editor:
            editor.AutoBatch(batcher)

            test_line_number = 1
            batch = self.subtitles.GetBatchContainingLine(test_line_number)
            self.assertIsNotNone(batch)
            assert batch is not None

            original_line = batch.GetOriginalLine(test_line_number)
            self.assertIsNotNone(original_line)
            assert original_line is not None

            # Update with same values
            result = editor.UpdateLine(test_line_number, {
                'text': original_line.text,
                'start': original_line.start,
                'end': original_line.end
            })

            self.assertLoggedFalse("no change update returned False", result)

    @skip_if_debugger_attached
    def test_update_line_invalid_line(self):
        """Test UpdateLine raises error for non-existent line"""
        batcher = SubtitleBatcher(self.options)

        with SubtitleEditor(self.subtitles) as editor:
            editor.AutoBatch(batcher)

            # Try to update non-existent line
            with self.assertRaises(ValueError) as context:
                editor.UpdateLine(999, {'text': 'Should fail'})

            error_message = str(context.exception)
            self.assertLoggedTrue(
                "error mentions line not found",
                "not found" in error_message.lower(),
                input_value=error_message,
            )

    @skip_if_debugger_attached
    def test_update_line_invalid_timing(self):
        """Test UpdateLine raises error for invalid timing"""
        batcher = SubtitleBatcher(self.options)

        with SubtitleEditor(self.subtitles) as editor:
            editor.AutoBatch(batcher)

            test_line_number = 1

            # Try to update with invalid start time
            with self.assertRaises(ValueError) as context:
                editor.UpdateLine(test_line_number, {'start': 'invalid time'})

            error_message = str(context.exception)
            self.assertLoggedTrue(
                "error mentions invalid time",
                "invalid" in error_message.lower(),
                input_value=error_message,
            )


if __name__ == '__main__':
    unittest.main()
