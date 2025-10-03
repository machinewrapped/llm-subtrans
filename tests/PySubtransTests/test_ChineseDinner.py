from __future__ import annotations

from datetime import timedelta

from PySubtrans.Helpers.TestCases import PrepareSubtitles, SubtitleTestCase
from PySubtrans.Helpers.ContextHelpers import GetBatchContext
from PySubtrans.Helpers.Tests import (
    log_info,
    log_input_expected_result,
    log_test_name,
    skip_if_debugger_attached,
)
from PySubtrans.SubtitleBatch import SubtitleBatch
from PySubtrans.SubtitleBatcher import SubtitleBatcher
from PySubtrans.SubtitleEditor import SubtitleEditor
from PySubtrans.Subtitles import Subtitles
from PySubtrans.Formats.SrtFileHandler import SrtFileHandler
from PySubtrans.SubtitleLine import SubtitleLine
from PySubtrans.SubtitleProject import SubtitleProject
from PySubtrans.SubtitleScene import SubtitleScene
from ..TestData.chinese_dinner import chinese_dinner_data

class ChineseDinnerTests(SubtitleTestCase):
    def __init__(self, methodName):
        super().__init__(methodName, custom_options={
            'max_batch_size': 100,
        })

    def test_ChineseDinner(self):

        subtitles : Subtitles = Subtitles()

        with self.subTest("Load subtitles from string"):
            log_test_name("Load subtitles from string")
            original_srt = chinese_dinner_data.get('original')
            if not original_srt or not isinstance(original_srt, str):
                self.fail("No original subtitles in test data")
                return

            subtitles.LoadSubtitlesFromString(original_srt, SrtFileHandler())
            self.assertIsNotNone(subtitles)

            if not subtitles or not subtitles.has_subtitles or not subtitles.originals:
                self.fail("Failed to load subtitles from string")
                return

            self.assertTrue(subtitles.has_subtitles)
            self.assertIsNotNone(subtitles.originals)

            self.assertEqual(subtitles.linecount, 64)
            self.assertEqual(subtitles.linecount, len(subtitles.originals))
            self.assertEqual(subtitles.scenecount, 0)
            self.assertEqual(subtitles.start_line_number, 1)
            self.assertSequenceEqual(subtitles.scenes, [])

        with self.subTest("Create project"):
            log_test_name("Create project")
            project = SubtitleProject()
            project.subtitles = subtitles
            project.UpdateProjectSettings(chinese_dinner_data)
            project.UpdateProjectSettings(self.options)

            self.assertIsNotNone(project.subtitles)

            self.assertEqual(project.target_language, self.options.target_language)
            self.assertEqual(project.movie_name, chinese_dinner_data.get('movie_name'))

            log_info("Movie name: " + (project.movie_name or "** No movie name**"))
            log_info("Target language: " + (project.target_language or "** No target language**"))

        with self.subTest("Test project settings"):
            log_test_name("Test project settings")
            project_settings = project.GetProjectSettings()

            self.assertEqual(project_settings.get('movie_name'), chinese_dinner_data.get('movie_name'))
            self.assertEqual(project_settings.get('description'), chinese_dinner_data.get('description'))
            self.assertEqual(project_settings.get('names'), chinese_dinner_data.get('names'))
            self.assertEqual(project_settings.get('target_language'), self.options.target_language)

            log_info("Description: " + (project_settings.get_str('description') or "** No description**"))
            log_info("Names: " + ", ".join(project_settings.get_list('names')))

    def test_SubtitleBatches(self):
        """
        Test subtitle batcher, batch context and batch merging
        """
        scene_count = 4
        scene_lengths = [30, 25, 6, 3]
        first_lines = [
            "いつものように食事が終わるまでは誰も入れないでくれ.",
            "選んで何を食事の後.",
            "お前どこの丸だ興味があるんだよ 殺し屋になるような人間ってのはどんなやつなのか",
            "本物の中華でもこうなのか."
        ]
        batch_containing_line = [(1, 1, 1), (10, 1,1), (32, 2, 1), (55, 2, 1), (63, 4, 1)]

        subtitles : Subtitles = PrepareSubtitles(chinese_dinner_data)

        batcher = SubtitleBatcher(self.options)
        with SubtitleEditor(subtitles) as editor:
            editor.AutoBatch(batcher)

        log_info("Line count: " + str(subtitles.linecount))
        log_info("Scene count: " + str(subtitles.scenecount))
        log_info("Scene batches" + ", ".join([str(scene.size) for scene in subtitles.scenes]))
        log_info("Scene line counts: " + ", ".join([str(scene.linecount) for scene in subtitles.scenes]))

        self.assertEqual(subtitles.scenecount, scene_count)

        for i in range(scene_count):
            scene_number = i+1
            scene : SubtitleScene = subtitles.GetScene(scene_number)
            self.assertIsNotNone(scene)
            assert scene is not None

            log_input_expected_result(f"Scene {scene.number} lines", scene_lengths[i], scene.linecount)
            self.assertEqual(scene_lengths[i], scene.linecount)

            if not scene.originals or len(scene.originals) == 0:
                self.fail(f"Scene {scene_number} has no batches")
                continue

            first_line = scene.originals[0]
            log_input_expected_result(f"First line", first_lines[i], first_line.text)
            self.assertEqual(first_lines[i], first_line.text)

        for line_number, scene_number, batch_number in batch_containing_line:
            batch = subtitles.GetBatchContainingLine(line_number)

            self.assertIsNotNone(batch)
            if not batch:
                self.fail(f"Failed to get batch containing line {line_number}")
                continue
            assert batch is not None

            log_input_expected_result(line_number, (scene_number, batch_number), (batch.scene, batch.number))
            self.assertEqual(scene_number, batch.scene)
            self.assertEqual(batch_number, batch.number)

            with self.subTest("Test batch context"):
                log_test_name("Test batch context")

                for scene in subtitles.scenes:
                    scene.AddContext('summary', f"Summary of scene {scene.number}")

                scene_4_context = GetBatchContext(subtitles, 4, 1, 10)
                self.assertIsNotNone(scene_4_context)

                self.assertEqual(scene_4_context.get('scene'), "Scene 4: Summary of scene 4")
                self.assertEqual(scene_4_context.get('batch'), "Batch 1")
                self.assertEqual(scene_4_context.get('movie_name'), chinese_dinner_data.get('movie_name'))
                self.assertEqual(scene_4_context.get('description'), chinese_dinner_data.get('description'))
                names_from_scene4 = scene_4_context.get('names', [])
                names_from_data = chinese_dinner_data.get_list('names')
                if isinstance(names_from_scene4, list):
                    self.assertSequenceEqual(names_from_scene4, names_from_data)
                else:
                    self.fail(f"Expected names to be list, got {type(names_from_scene4)}")
                history_from_scene4 = scene_4_context.get('history', [])
                if isinstance(history_from_scene4, list):
                    self.assertSequenceEqual(history_from_scene4, [
                        "scene 1: Summary of scene 1",
                        "scene 2: Summary of scene 2",
                        "scene 3: Summary of scene 3"
                        ])
                else:
                    self.fail(f"Expected history to be list, got {type(history_from_scene4)}")
                    return

        with self.subTest("Merge scenes 3 and 4"):
            log_test_name("Merge scenes tests")

            # Merge scenes 3 and 4
            with SubtitleEditor(subtitles) as editor:
                editor.MergeScenes([3,4])

            log_input_expected_result(f"Merge [3,4] -> scenecount", 3, subtitles.scenecount)
            self.assertEqual(subtitles.scenecount, 3)

            merged_scene : SubtitleScene = subtitles.GetScene(3)
            self.assertIsNotNone(merged_scene)
            assert merged_scene is not None
            log_input_expected_result("Batch count", 2, merged_scene.size)
            self.assertEqual(merged_scene.size, 2)
            log_input_expected_result("Line count", 9, merged_scene.linecount)
            self.assertEqual(merged_scene.linecount, 9)
            log_input_expected_result("First line number", 56, merged_scene.first_line_number)
            self.assertEqual(merged_scene.first_line_number, 56)
            log_input_expected_result("Last line number", 64, merged_scene.last_line_number)
            self.assertEqual(merged_scene.last_line_number, 64)

            first_batch : SubtitleBatch|None = merged_scene.GetBatch(1)
            self.assertIsNotNone(first_batch, "First batch should exist after merge")
            assert first_batch is not None  # Type narrowing for PyLance
            log_input_expected_result("Batch 1", (3, 1), (first_batch.scene, first_batch.number))
            self.assertEqual(first_batch.scene, 3)
            self.assertEqual(first_batch.number, 1)
            log_input_expected_result("First line number", 56, first_batch.first_line_number)
            self.assertEqual(first_batch.first_line_number, 56)
            log_input_expected_result("Last line number", 61, first_batch.last_line_number)
            self.assertEqual(first_batch.last_line_number, 61)

            first_batch_context = GetBatchContext(subtitles, 3, 1, 10)
            self.assertIsNotNone(first_batch_context)
            self.assertEqual(first_batch_context.get('scene'), "Scene 3: Summary of scene 3\nSummary of scene 4")
            self.assertEqual(first_batch_context.get('batch'), "Batch 1")
            self.assertEqual(first_batch_context.get('movie_name'), chinese_dinner_data.get('movie_name'))
            self.assertEqual(first_batch_context.get('description'), chinese_dinner_data.get('description'))
            names_from_context = first_batch_context.get('names', [])
            names_from_data = chinese_dinner_data.get_list('names')
            if isinstance(names_from_context, list):
                self.assertSequenceEqual(names_from_context, names_from_data)
            else:
                self.fail(f"Expected names to be list, got {type(names_from_context)}")
            history_from_context = first_batch_context.get('history', [])
            if isinstance(history_from_context, list):
                self.assertSequenceEqual(history_from_context, [
                    "scene 1: Summary of scene 1",
                    "scene 2: Summary of scene 2"
                    ])
            else:
                self.fail(f"Expected history to be list, got {type(history_from_context)}")

            # Add a summary for the first batch
            first_batch.summary = "Summary of batch 1"

            second_batch : SubtitleBatch|None = subtitles.GetBatchContainingLine(62)
            self.assertIsNotNone(second_batch, "Second batch should exist")
            assert second_batch is not None  # Type narrowing for PyLance
            log_input_expected_result("Line 61 in batch", (3, 2), (second_batch.scene, second_batch.number))
            self.assertEqual(second_batch.scene, 3)
            self.assertEqual(second_batch.number, 2)
            log_input_expected_result("First line number", 62, second_batch.first_line_number)
            self.assertEqual(second_batch.first_line_number, 62)
            log_input_expected_result("Last line number", 64, second_batch.last_line_number)
            self.assertEqual(second_batch.last_line_number, 64)

            second_batch_context = GetBatchContext(subtitles, 3, 2, 10)
            self.assertIsNotNone(second_batch_context)

            self.assertEqual(second_batch_context.get('scene'), "Scene 3: Summary of scene 3\nSummary of scene 4")
            self.assertEqual(second_batch_context.get('batch'), "Batch 2")
            self.assertEqual(second_batch_context.get('movie_name'), chinese_dinner_data.get('movie_name'))
            self.assertEqual(second_batch_context.get('description'), chinese_dinner_data.get('description'))
            names_from_context = second_batch_context.get('names', [])
            names_from_data = chinese_dinner_data.get_list('names')
            if isinstance(names_from_context, list):
                self.assertSequenceEqual(names_from_context, names_from_data)
            else:
                self.fail(f"Expected names to be list, got {type(names_from_context)}")
            history_from_context = second_batch_context.get('history', [])
            if isinstance(history_from_context, list):
                self.assertSequenceEqual(history_from_context, [
                    "scene 1: Summary of scene 1",
                    "scene 2: Summary of scene 2",
                    "scene 3 batch 1: Summary of batch 1"
                    ])
            else:
                self.fail(f"Expected history to be list, got {type(history_from_context)}")

            second_batch.summary = "Summary of batch 2"

        with self.subTest("Merge batches"):
            log_test_name("Merge scene 3 batches 1 & 2")
            with SubtitleEditor(subtitles) as editor:
                editor.MergeBatches(3, [1,2])

            log_input_expected_result("Scene count", 3, subtitles.scenecount)
            self.assertEqual(subtitles.scenecount, 3)

            log_input_expected_result("Batch count", 1, merged_scene.size)
            self.assertEqual(merged_scene.size, 1)

            log_input_expected_result("Scene line count", 9, merged_scene.linecount)
            self.assertEqual(merged_scene.linecount, 9)

            merged_batch : SubtitleBatch|None = merged_scene.GetBatch(1)
            self.assertIsNotNone(merged_batch, "Merged batch should exist")
            assert merged_batch is not None  # Type narrowing for PyLance

            log_input_expected_result("Batch line count", 9, merged_batch.size)
            self.assertEqual(merged_batch.size, 9)

            self.assertEqual(merged_batch.first_line_number, 56)
            self.assertEqual(merged_batch.last_line_number, 64)

            self.assertEqual(merged_batch.summary, "Summary of batch 1\nSummary of batch 2")

            merged_batch_context = GetBatchContext(subtitles, 3, 1, 10)
            self.assertIsNotNone(merged_batch_context)

            self.assertEqual(merged_batch_context.get('scene'), "Scene 3: Summary of scene 3\nSummary of scene 4")
            self.assertEqual(merged_batch_context.get('batch'), "Batch 1: Summary of batch 1\nSummary of batch 2")
            self.assertEqual(merged_batch_context.get('movie_name'), chinese_dinner_data.get('movie_name'))
            self.assertEqual(merged_batch_context.get('description'), chinese_dinner_data.get('description'))
            names_from_context = merged_batch_context.get('names', [])
            names_from_data = chinese_dinner_data.get_list('names')
            if isinstance(names_from_context, list):
                self.assertSequenceEqual(names_from_context, names_from_data)
            else:
                self.fail(f"Expected names to be list, got {type(names_from_context)}")
            history_from_context = merged_batch_context.get('history', [])
            if isinstance(history_from_context, list):
                self.assertSequenceEqual(history_from_context, [
                    "scene 1: Summary of scene 1",
                    "scene 2: Summary of scene 2",
                    ])
            else:
                self.fail(f"Expected history to be list, got {type(history_from_context)}")

        with self.subTest("Auto-split scene 1, batch 1"):
            log_test_name("Auto-split scene 1, batch 1")
            scene_1 = subtitles.GetScene(1)
            self.assertIsNotNone(scene_1)

            min_batch_size = 5
            scene_1.AutoSplitBatch(1, min_batch_size)

            log_input_expected_result("Scene count", 3, subtitles.scenecount)
            self.assertEqual(subtitles.scenecount, 3)

            log_input_expected_result("Scene 1 batches", 2, scene_1.size)
            self.assertEqual(scene_1.size, 2)

            expected_batch_sizes = [14, 16]
            expected_first_lines = [
                (1, "いつものように食事が終わるまでは誰も入れないでくれ."),
                (15, "俺は肩にだぞ.")
            ]

            for i in range(2):
                batch = scene_1.GetBatch(i+1)
                self.assertIsNotNone(batch, f"Batch {i+1} should exist after auto-split")
                assert batch is not None  # Type narrowing for PyLance

                log_input_expected_result(f"Batch {batch.number} size", expected_batch_sizes[i], batch.size)
                self.assertEqual(expected_batch_sizes[i], batch.size)

                log_input_expected_result(f"First line ", expected_first_lines[i], (batch.first_line_number, batch.originals[0].text))
                self.assertEqual(expected_first_lines[i][0], batch.first_line_number)
                self.assertEqual(expected_first_lines[i][1], batch.originals[0].text)

        with self.subTest("Split scene 1"):
            log_test_name("Split scene 1")

            with SubtitleEditor(subtitles) as editor:
                editor.SplitScene(1, 2)

            log_input_expected_result("Scene count", 4, subtitles.scenecount)
            self.assertEqual(subtitles.scenecount, 4)

            scene_1 = subtitles.GetScene(1)
            self.assertIsNotNone(scene_1)

            log_input_expected_result("Scene 1 batches", (1, 14), (scene_1.size, scene_1.linecount))
            self.assertEqual(scene_1.size, 1)
            self.assertEqual(scene_1.linecount, 14)
            self.assertEqual(scene_1.first_line_number, 1)
            self.assertEqual(scene_1.last_line_number, 14)

            scene_2 = subtitles.GetScene(2)
            self.assertIsNotNone(scene_2)

            log_input_expected_result("Scene 2 batches", (1, 16), (scene_2.size, scene_2.linecount))
            self.assertEqual(scene_2.size, 1)
            self.assertEqual(scene_2.linecount, 16)
            self.assertEqual(scene_2.first_line_number, 15)
            self.assertEqual(scene_2.last_line_number, 30)

    def test_SubtitleLine(self):
        """
        Test fetching and modifying a subtitle line
        """
        subtitles = PrepareSubtitles(chinese_dinner_data)

        line : SubtitleLine|None = subtitles.GetOriginalLine(36)
        self.assertIsNotNone(line, "Line 36 should exist")
        assert line is not None  # Type narrowing for PyLance

        log_info(f"Line {line.number}: {line.text}")

        self.assertEqual(line.number, 36)
        self.assertEqual(line.srt_start, "00:15:35,590")
        self.assertEqual(line.srt_end, "00:15:36,790")
        self.assertEqual(line.text, "どうして俺を殺すんだ.")

        # Update line text directly (since this is testing specific line operations)
        line.text = "どうして俺を殺すのか."
        line.translation = "Why are you going to kill me?"

        log_input_expected_result("After update", "どうして俺を殺すのか.", line.text)
        log_input_expected_result("Translated", "Why are you going to kill me?", line.translation)

        self.assertEqual(line.text, "どうして俺を殺すのか.")
        self.assertEqual(line.translation, "Why are you going to kill me?")

    def test_SubtitleEditor_UpdateLine(self):
        """
        Test SubtitleEditor.UpdateLine functionality with real subtitle data
        """
        subtitles = PrepareSubtitles(chinese_dinner_data)

        batcher = SubtitleBatcher(self.options)
        with SubtitleEditor(subtitles) as editor:
            editor.AutoBatch(batcher)

        with self.subTest("Update line text and translation"):
            log_test_name("Update line text and translation")

            test_line_number = 36
            original_line = subtitles.GetOriginalLine(test_line_number)
            self.assertIsNotNone(original_line, f"Line {test_line_number} should exist")
            assert original_line is not None

            original_text = original_line.text
            original_start = original_line.start
            original_end = original_line.end

            log_info(f"Original line {test_line_number}: {original_text}")

            new_text = "どうして俺を殺すのか."
            new_translation = "Why are you going to kill me?"
            new_metadata = {"speaker": "protagonist", "emotion": "fearful"}

            with SubtitleEditor(subtitles) as editor:
                result = editor.UpdateLine(test_line_number, {
                    'text': new_text,
                    'translation': new_translation,
                    'metadata': new_metadata
                })

                log_input_expected_result("UpdateLine returned True", True, result)
                self.assertTrue(result)

            # Verify changes were applied
            updated_line = subtitles.GetOriginalLine(test_line_number)
            self.assertIsNotNone(updated_line)
            assert updated_line is not None

            log_input_expected_result("Line text updated", new_text, updated_line.text)
            log_input_expected_result("Line translation updated", new_translation, updated_line.translation)
            log_input_expected_result("Line metadata updated", new_metadata, updated_line.metadata)

            self.assertEqual(updated_line.text, new_text)
            self.assertEqual(updated_line.translation, new_translation)
            self.assertEqual(updated_line.metadata, new_metadata)

            # Verify timing was preserved
            log_input_expected_result("Start time preserved", original_start, updated_line.start)
            log_input_expected_result("End time preserved", original_end, updated_line.end)
            self.assertEqual(updated_line.start, original_start)
            self.assertEqual(updated_line.end, original_end)

            # Verify translated line was created in batch
            batch = subtitles.GetBatchContainingLine(test_line_number)
            self.assertIsNotNone(batch)
            assert batch is not None
            translated_line = batch.GetTranslatedLine(test_line_number)
            log_input_expected_result("Translated line created", True, translated_line is not None)
            self.assertIsNotNone(translated_line)

            if translated_line:
                log_input_expected_result("Translated line text", new_translation, translated_line.text)
                log_input_expected_result("Translated line original reference", new_text, translated_line.original)
                self.assertEqual(translated_line.text, new_translation)
                self.assertEqual(translated_line.original, new_text)

        with self.subTest("Update line timing"):
            log_test_name("Update line timing")

            test_line_number = 10
            batch = subtitles.GetBatchContainingLine(test_line_number)
            self.assertIsNotNone(batch)
            assert batch is not None

            original_line = batch.GetOriginalLine(test_line_number)
            self.assertIsNotNone(original_line)
            assert original_line is not None

            new_start = timedelta(seconds=30, milliseconds=500)
            new_end = timedelta(seconds=33, milliseconds=750)

            with SubtitleEditor(subtitles) as editor:
                result = editor.UpdateLine(test_line_number, {
                    'start': new_start,
                    'end': new_end
                })

                log_input_expected_result("Timing update returned True", True, result)
                self.assertTrue(result)

            # Verify timing was updated
            updated_line = batch.GetOriginalLine(test_line_number)
            assert updated_line is not None
            log_input_expected_result("Start time updated", new_start, updated_line.start)
            log_input_expected_result("End time updated", new_end, updated_line.end)
            self.assertEqual(updated_line.start, new_start)
            self.assertEqual(updated_line.end, new_end)

        with self.subTest("Update existing translation"):
            log_test_name("Update existing translation")

            test_line_number = 36  # Use line we already added translation to
            batch = subtitles.GetBatchContainingLine(test_line_number)
            self.assertIsNotNone(batch)
            assert batch is not None

            # Verify translation exists from previous test
            existing_translated_line = batch.GetTranslatedLine(test_line_number)
            self.assertIsNotNone(existing_translated_line)

            updated_translation = "Why would you kill me?"

            with SubtitleEditor(subtitles) as editor:
                result = editor.UpdateLine(test_line_number, {
                    'translation': updated_translation
                })

                log_input_expected_result("Translation update returned True", True, result)
                self.assertTrue(result)

            # Verify translation was updated
            updated_translated_line = batch.GetTranslatedLine(test_line_number)
            assert updated_translated_line is not None
            log_input_expected_result("Translation text updated", updated_translation, updated_translated_line.text)
            self.assertEqual(updated_translated_line.text, updated_translation)

            # Verify original line also reflects change
            original_line = batch.GetOriginalLine(test_line_number)
            assert original_line is not None
            log_input_expected_result("Original line translation property", updated_translation, original_line.translation)
            self.assertEqual(original_line.translation, updated_translation)

        with self.subTest("No-change update"):
            log_test_name("No-change update")

            test_line_number = 1
            batch = subtitles.GetBatchContainingLine(test_line_number)
            self.assertIsNotNone(batch)
            assert batch is not None

            original_line = batch.GetOriginalLine(test_line_number)
            self.assertIsNotNone(original_line)
            assert original_line is not None

            # Update with same values
            with SubtitleEditor(subtitles) as editor:
                result = editor.UpdateLine(test_line_number, {
                    'text': original_line.text,
                    'start': original_line.start,
                    'end': original_line.end
                })

                log_input_expected_result("No-change update returned False", False, result)
                self.assertFalse(result)

    @skip_if_debugger_attached
    def test_SubtitleEditor_UpdateLine_error_handling(self):
        """Tests error handling paths for SubtitleEditor.UpdateLine"""
        subtitles = PrepareSubtitles(chinese_dinner_data)

        batcher = SubtitleBatcher(self.options)
        with SubtitleEditor(subtitles) as editor:
            editor.AutoBatch(batcher)

        with self.subTest("Non-existent line"):
            log_test_name("UpdateLine error: non-existent line")

            with SubtitleEditor(subtitles) as editor:
                with self.assertRaises(ValueError) as context:
                    editor.UpdateLine(999, {'text': 'Should fail'})

            error_message = str(context.exception)
            log_input_expected_result("Error mentions line not found", True, "not found" in error_message.lower())
            self.assertIn("not found", error_message.lower())

        with self.subTest("Invalid timing"):
            log_test_name("UpdateLine error: invalid timing")

            with SubtitleEditor(subtitles) as editor:
                with self.assertRaises(ValueError) as context:
                    editor.UpdateLine(1, {'start': 'invalid time format'})

            error_message = str(context.exception)
            log_input_expected_result("Error mentions invalid time", True, "invalid" in error_message.lower())
            self.assertIn("invalid", error_message.lower())

