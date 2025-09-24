import os
import tempfile
import unittest

from PySubtrans import (
    SubtitleBuilder,
    SubtitleTranslator,
    TranslationProvider,
    batch_subtitles,
    init_options,
    init_project,
    init_subtitles,
    init_translator,
    init_translation_provider,
)
from PySubtrans.Helpers.TestCases import DummyProvider  # noqa: F401 - ensure provider is registered
from PySubtrans.UnitTests.TestData.chinese_dinner import chinese_dinner_json_data
from PySubtrans.Helpers.Tests import (
    log_input_expected_error,
    log_input_expected_result,
    log_test_name,
    skip_if_debugger_attached,
)
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import SubtitleError, TranslationImpossibleError


class PySubtransConvenienceTests(unittest.TestCase):
    def setUp(self) -> None:
        log_test_name(self._testMethodName)
        self.srt_content = """1\n00:00:01,000 --> 00:00:04,000\nHello world\n\n2\n00:00:06,000 --> 00:00:09,000\nHow are you?\n"""

    def _create_options(self):
        options = init_options(
            provider="Dummy Provider",
            model="dummy-model",
            prompt="Translate test subtitles",
            movie_name="Test Movie",
            description="A short description",
            names=["Alice", "Bob"],
            target_language="Spanish",
            preview=True,
            preprocess_subtitles=True,
            scene_threshold=20.0,
            min_batch_size=1,
            max_batch_size=5,
        )

        options.provider_settings['Dummy Provider'] = SettingsType({'data': {'names': ['Alice', 'Bob']}})
        return options

    def test_batch_subtitles_required_for_translation(self) -> None:
        options = self._create_options()
        manual_options = init_options(preprocess_subtitles=False)

        subtitles = init_subtitles(
            filepath=None,
            content=self.srt_content,
            options=manual_options,
            auto_batch=False,
        )
        subtitles.UpdateSettings(SettingsType({
            'movie_name': 'Test Movie',
            'description': 'A short description',
            'names': ['Alice', 'Bob'],
            'target_language': 'Spanish',
        }))

        translator = init_translator(options)

        if skip_if_debugger_attached("test_batch_subtitles_required_for_translation"):
            return

        with self.assertRaises(TranslationImpossibleError) as exc:
            translator.TranslateSubtitles(subtitles)

        log_input_expected_error("Translate without batching", TranslationImpossibleError, exc.exception)

        scenes = batch_subtitles(subtitles, scene_threshold=20.0, min_batch_size=1, max_batch_size=5)

        log_input_expected_result("scene count after batching", 1, len(scenes))
        self.assertEqual(len(scenes), 1)

        log_input_expected_result("batch count after batching", 1, len(scenes[0].batches))
        self.assertEqual(len(scenes[0].batches), 1)

        translator.TranslateSubtitles(subtitles)

        log_input_expected_result("scene count remains", 1, subtitles.scenecount)
        self.assertEqual(subtitles.scenecount, 1)

    def test_init_subtitles_auto_batches(self) -> None:
        options = self._create_options()

        subtitles = init_subtitles(
            filepath=None,
            content=self.srt_content,
            options=options,
        )

        log_input_expected_result("auto batch created scenes", True, subtitles.scenecount > 0)
        self.assertGreater(subtitles.scenecount, 0)

        batch_count = sum(len(scene.batches) for scene in subtitles.scenes)
        log_input_expected_result("auto batch created batches", True, batch_count > 0)
        self.assertGreater(batch_count, 0)

        preprocess_setting = subtitles.settings.get('preprocess_subtitles')
        log_input_expected_result(
            "preprocess flag stored on subtitles",
            None,
            preprocess_setting,
        )
        self.assertIsNone(preprocess_setting)

        scene_threshold = subtitles.settings.get('scene_threshold')
        log_input_expected_result(
            "scene threshold stored on subtitles",
            None,
            scene_threshold,
        )
        self.assertIsNone(scene_threshold)

    def test_init_translation_provider_reuse(self) -> None:
        options = self._create_options()

        provider_settings = options.provider_settings['Dummy Provider']
        provider_settings['data'] = {
            'names': ['Alice', 'Bob'],
            'response_map': {},
        }

        provider = init_translation_provider("Dummy Provider", options)

        log_input_expected_result("provider initialised", "Dummy Provider", provider.name)
        self.assertEqual(provider.name, "Dummy Provider")

        translator = init_translator(options, translation_provider=provider)

        log_input_expected_result(
            "translator provider reused",
            provider.name,
            translator.translation_provider.name,
        )
        self.assertIs(translator.translation_provider, provider)

    def test_init_translation_provider_updates_provider(self) -> None:
        options = init_options(model="dummy-model")

        log_input_expected_result("options provider before init", None, options.provider)
        self.assertIsNone(options.provider)

        provider = init_translation_provider("Dummy Provider", options)

        log_input_expected_result("options provider after init", "Dummy Provider", options.provider)
        self.assertEqual(options.provider, "Dummy Provider")

        log_input_expected_result("provider instance name", "Dummy Provider", provider.name)
        self.assertEqual(provider.name, "Dummy Provider")

        log_input_expected_result(
            "provider settings created",
            True,
            "Dummy Provider" in options.provider_settings,
        )
        self.assertIn("Dummy Provider", options.provider_settings)

        provider_options = options.provider_settings['Dummy Provider']
        log_input_expected_result(
            "provider model stored",
            "dummy-model",
            provider_options.get('model'),
        )
        self.assertEqual(provider_options.get('model'), "dummy-model")

    def test_init_project_batches_on_creation(self) -> None:
        options = self._create_options()

        with tempfile.NamedTemporaryFile('w', suffix='.srt', delete=False) as handle:
            handle.write(self.srt_content)
            subtitle_path = handle.name

        try:
            project = init_project(options, filepath=subtitle_path)

            log_input_expected_result("scenes created", True, project.subtitles.scenecount > 0)
            self.assertGreater(project.subtitles.scenecount, 0)
            batch_count = sum(len(scene.batches) for scene in project.subtitles.scenes)
            log_input_expected_result("batches created", True, batch_count > 0)
            self.assertGreater(batch_count, 0)

            log_input_expected_result(
                "project options preprocess flag",
                True,
                options.get_bool('preprocess_subtitles'),
            )
            self.assertTrue(options.get_bool('preprocess_subtitles'))

            preprocess_setting = project.subtitles.settings.get('preprocess_subtitles')
            log_input_expected_result(
                "project subtitles preprocess flag",
                None,
                preprocess_setting,
            )
            self.assertIsNone(preprocess_setting)

            scene_threshold = project.subtitles.settings.get('scene_threshold')
            log_input_expected_result("project subtitles scene threshold", None, scene_threshold)
            self.assertIsNone(scene_threshold)

        finally:
            if os.path.exists(subtitle_path):
                os.remove(subtitle_path)


    def test_json_workflow_with_events(self) -> None:
        """Test the JSON workflow example from README documentation"""
        options = self._create_options()

        # Use the realistic test JSON data from chinese_dinner module
        json_data = chinese_dinner_json_data

        log_input_expected_result("JSON scenes loaded", True, len(json_data["scenes"]) > 0)
        self.assertGreater(len(json_data["scenes"]), 0)

        # Build subtitles from JSON using SubtitleBuilder
        builder = SubtitleBuilder(max_batch_size=5)  # Small batch size to test multiple batches

        total_lines = 0
        for scene_data in json_data["scenes"]:
            builder.AddScene(summary=scene_data["summary"])

            for line_data in scene_data["lines"]:
                builder.BuildLine(
                    start=line_data["start"],
                    end=line_data["end"],
                    text=line_data["text"]
                )
                total_lines += 1

        subtitles = builder.Build()

        # Set movie name from JSON data for the translator
        subtitles.UpdateSettings(SettingsType({
            'movie_name': json_data.get('movie_name', 'Test Movie'),
            'description': json_data.get('description', 'Test description'),
            'names': json_data.get('names', []),
            'target_language': json_data.get('target_language', 'English'),
        }))

        log_input_expected_result("built subtitles line count", total_lines, subtitles.linecount)
        self.assertEqual(subtitles.linecount, total_lines)

        log_input_expected_result("built subtitles scene count", len(json_data["scenes"]), subtitles.scenecount)
        self.assertEqual(subtitles.scenecount, len(json_data["scenes"]))

        # Verify scenes have summaries
        for i, scene in enumerate(subtitles.scenes):
            expected_summary = json_data["scenes"][i]["summary"]
            log_input_expected_result(f"scene {scene.number} summary", expected_summary, scene.context.get('summary'))
            self.assertEqual(scene.context.get('summary'), expected_summary)

        # The SubtitleBatcher creates batches based on timing gaps, not just max_batch_size
        # So we just verify we have a reasonable number of batches
        actual_batch_count = sum(len(scene.batches) for scene in subtitles.scenes)

        log_input_expected_result("total batch count", True, actual_batch_count >= len(json_data["scenes"]))
        self.assertGreaterEqual(actual_batch_count, len(json_data["scenes"]))  # At least one batch per scene

        # Verify scene 1 has multiple batches (since it has 55 lines with max_batch_size=5)
        scene1_batch_count = len(subtitles.scenes[0].batches)
        log_input_expected_result("scene 1 multiple batches", True, scene1_batch_count > 1)
        self.assertGreater(scene1_batch_count, 1)

        # Test event system with translation
        translation_provider = TranslationProvider.get_provider(options)
        translator = SubtitleTranslator(options, translation_provider)

        batch_events = []
        scene_events = []

        def on_batch_translated(batch):
            batch_events.append({
                'scene': batch.scene,
                'batch': batch.number,
                'size': batch.size,
                'summary': batch.summary
            })

        def on_scene_translated(scene):
            scene_events.append({
                'scene': scene.number,
                'summary': scene.summary,
                'linecount': scene.linecount,
                'batch_count': scene.size
            })

        # Subscribe to events
        translator.events.batch_translated += on_batch_translated
        translator.events.scene_translated += on_scene_translated

        # Execute translation
        translator.TranslateSubtitles(subtitles)

        # Verify events were fired
        log_input_expected_result("batch events fired", actual_batch_count, len(batch_events))
        self.assertEqual(len(batch_events), actual_batch_count)

        log_input_expected_result("scene events fired", len(json_data["scenes"]), len(scene_events))
        self.assertEqual(len(scene_events), len(json_data["scenes"]))

        # Verify event data accuracy
        for event in batch_events:
            log_input_expected_result(f"batch event scene {event['scene']} size", True, event['size'] > 0)
            self.assertGreater(event['size'], 0)

        for i, event in enumerate(scene_events):
            expected_scene_num = i + 1
            log_input_expected_result(f"scene event {i} number", expected_scene_num, event['scene'])
            self.assertEqual(event['scene'], expected_scene_num)

            log_input_expected_result(f"scene event {i} linecount", True, event['linecount'] > 0)
            self.assertGreater(event['linecount'], 0)

        # Note: Translation may fail due to dummy provider limitations, but events should still fire
        # Just verify that we tried to translate (events fired properly)
        log_input_expected_result("translation attempted", True, len(batch_events) > 0)
        self.assertGreater(len(batch_events), 0)

        log_input_expected_result("scene processing completed", True, len(scene_events) > 0)
        self.assertGreater(len(scene_events), 0)

    def test_explicit_prompt_overrides_instruction_file(self) -> None:
        """Test that explicit prompts take precedence over instruction file prompts"""
        # Create a temporary instruction file with a different prompt
        with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False, encoding='utf-8') as handle:
            handle.write("### prompt\nTranslate these subtitles from instruction file\n\n")
            handle.write("### instructions\nDefault instructions from file\n\n")
            handle.write("### retry_instructions\nDefault retry instructions from file\n")
            instruction_file_path = handle.name

        try:
            explicit_prompt = "My explicit custom prompt"

            # Test with explicit prompt - should override instruction file
            options = init_options(
                provider="Dummy Provider",
                model="dummy-model",
                prompt=explicit_prompt,
                instruction_file=instruction_file_path
            )

            log_input_expected_result("explicit prompt used", explicit_prompt, options.get('prompt'))
            self.assertEqual(options.get('prompt'), explicit_prompt)

            # Test without explicit prompt - should use instruction file
            options_no_prompt = init_options(
                provider="Dummy Provider",
                model="dummy-model",
                instruction_file=instruction_file_path
            )

            log_input_expected_result("instruction file prompt used", "Translate these subtitles from instruction file", options_no_prompt.get('prompt'))
            self.assertEqual(options_no_prompt.get('prompt'), "Translate these subtitles from instruction file")

        finally:
            if os.path.exists(instruction_file_path):
                os.remove(instruction_file_path)

    def test_init_translator_respects_user_modifications(self) -> None:
        """Test that init_translator respects modifications made between init_options and init_translator"""
        options = init_options(
            provider="Dummy Provider",
            model="dummy-model",
            prompt="Original prompt"
        )

        # User modifies the prompt after init_options
        user_modified_prompt = "User modified prompt after init_options"
        options['prompt'] = user_modified_prompt

        # init_translator should NOT call InitialiseInstructions and should preserve user changes
        translator = init_translator(options)

        log_input_expected_result("user modified prompt preserved", user_modified_prompt, translator.settings.get('prompt'))
        self.assertEqual(translator.settings.get('prompt'), user_modified_prompt)

    def test_instruction_file_without_explicit_prompt(self) -> None:
        """Test that instruction file values are used when no explicit prompt is provided"""
        # Create a temporary instruction file
        with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False, encoding='utf-8') as handle:
            handle.write("### prompt\nInstruction file prompt\n\n")
            handle.write("### instructions\nInstruction file instructions\n\n")
            handle.write("### target_language\nFrench\n\n")
            handle.write("### task_type\nCustomTask\n")
            instruction_file_path = handle.name

        try:
            # Test that all instruction file values are loaded when no explicit values provided
            options = init_options(
                provider="Dummy Provider",
                model="dummy-model",
                instruction_file=instruction_file_path
            )

            log_input_expected_result("instruction file prompt", "Instruction file prompt", options.get('prompt'))
            self.assertEqual(options.get('prompt'), "Instruction file prompt")

            log_input_expected_result("instruction file instructions", "Instruction file instructions", options.get('instructions'))
            self.assertEqual(options.get('instructions'), "Instruction file instructions")

            log_input_expected_result("instruction file target_language", "French", options.get('target_language'))
            self.assertEqual(options.get('target_language'), "French")

            log_input_expected_result("instruction file task_type", "CustomTask", options.get('task_type'))
            self.assertEqual(options.get('task_type'), "CustomTask")

        finally:
            if os.path.exists(instruction_file_path):
                os.remove(instruction_file_path)


if __name__ == '__main__':
    unittest.main()
