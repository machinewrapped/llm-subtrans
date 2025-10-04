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
from PySubtrans.Helpers.TestCases import DummyProvider, LoggedTestCase  # noqa: F401 - ensure provider is registered
from ..TestData.chinese_dinner import chinese_dinner_json_data
from PySubtrans.Helpers.Tests import (
    log_input_expected_error,
    skip_if_debugger_attached,
)
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import SubtitleError, TranslationImpossibleError


class PySubtransConvenienceTests(LoggedTestCase):
    def setUp(self) -> None:
        super().setUp()
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

    @skip_if_debugger_attached
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

        with self.assertRaises(TranslationImpossibleError) as exc:
            translator.TranslateSubtitles(subtitles)

        log_input_expected_error("Translate without batching", TranslationImpossibleError, exc.exception)

        scenes = batch_subtitles(subtitles, scene_threshold=20.0, min_batch_size=1, max_batch_size=5)
        self.assertLoggedEqual("scene count after batching", 1, len(scenes))

        self.assertLoggedEqual("batch count after batching", 1, len(scenes[0].batches))

        translator.TranslateSubtitles(subtitles)

        self.assertLoggedEqual("scene count remains", 1, subtitles.scenecount)

    def test_init_subtitles_auto_batches(self) -> None:
        options = self._create_options()

        subtitles = init_subtitles(
            filepath=None,
            content=self.srt_content,
            options=options,
        )

        self.assertLoggedGreater(
            "auto batch created scenes",
            subtitles.scenecount,
            0,
        )

        batch_count = sum(len(scene.batches) for scene in subtitles.scenes)
        self.assertLoggedGreater(
            "auto batch created batches",
            batch_count,
            0,
        )

        preprocess_setting = subtitles.settings.get('preprocess_subtitles')
        self.assertLoggedIsNone("preprocess flag stored on subtitles", preprocess_setting)

        scene_threshold = subtitles.settings.get('scene_threshold')
        self.assertLoggedIsNone("scene threshold stored on subtitles", scene_threshold)

    def test_init_translation_provider_reuse(self) -> None:
        options = self._create_options()

        provider_settings = options.provider_settings['Dummy Provider']
        provider_settings['data'] = {
            'names': ['Alice', 'Bob'],
            'response_map': {},
        }

        provider = init_translation_provider("Dummy Provider", options)

        self.assertLoggedEqual("provider initialised", "Dummy Provider", provider.name)

        translator = init_translator(options, translation_provider=provider)

        self.assertLoggedIs(
            "translator provider reused",
            provider,
            translator.translation_provider,
        )

    def test_init_translation_provider_updates_provider(self) -> None:
        options = init_options(model="dummy-model")

        self.assertLoggedIsNone("options provider before init", options.provider)

        provider = init_translation_provider("Dummy Provider", options)

        self.assertLoggedEqual("options provider after init", "Dummy Provider", options.provider)

        self.assertLoggedEqual("provider instance name", "Dummy Provider", provider.name)

        self.assertLoggedIn("provider settings created", "Dummy Provider", options.provider_settings)

        provider_options = options.provider_settings['Dummy Provider']
        self.assertLoggedEqual("provider model stored", "dummy-model", provider_options.get('model'))

    def test_init_project_batches_on_creation(self) -> None:
        options = self._create_options()

        with tempfile.NamedTemporaryFile('w', suffix='.srt', delete=False) as handle:
            handle.write(self.srt_content)
            subtitle_path = handle.name

        try:
            project = init_project(options, filepath=subtitle_path)

            self.assertLoggedGreater(
                "project scenes created",
                project.subtitles.scenecount,
                0,
            )
            batch_count = sum(len(scene.batches) for scene in project.subtitles.scenes)
            self.assertLoggedGreater(
                "project batches created",
                batch_count,
                0,
            )

            self.assertLoggedTrue(
                "project options preprocess flag",
                options.get_bool('preprocess_subtitles'),
            )

            preprocess_setting = project.subtitles.settings.get('preprocess_subtitles')
            self.assertLoggedIsNone("project subtitles preprocess flag", preprocess_setting)

            scene_threshold = project.subtitles.settings.get('scene_threshold')
            self.assertLoggedIsNone("project subtitles scene threshold", scene_threshold)

        finally:
            if os.path.exists(subtitle_path):
                os.remove(subtitle_path)


    def test_json_workflow_with_events(self) -> None:
        """Test the JSON workflow example from README documentation"""
        options = self._create_options()

        # Use the realistic test JSON data from chinese_dinner module
        json_data = chinese_dinner_json_data

        self.assertLoggedGreater(
            "JSON scenes loaded",
            len(json_data["scenes"]),
            0,
        )

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

        self.assertLoggedEqual("built subtitles line count", total_lines, subtitles.linecount)

        self.assertLoggedEqual("built subtitles scene count", len(json_data["scenes"]), subtitles.scenecount)

        # Verify scenes have summaries
        for i, scene in enumerate(subtitles.scenes):
            expected_summary = json_data["scenes"][i]["summary"]
            self.assertLoggedEqual(
                f"scene {scene.number} summary",
                expected_summary,
                scene.context.get('summary')
            )

        # The SubtitleBatcher creates batches based on timing gaps, not just max_batch_size
        # So we just verify we have a reasonable number of batches
        actual_batch_count = sum(len(scene.batches) for scene in subtitles.scenes)

        self.assertLoggedGreaterEqual(
            "total batch count",
            actual_batch_count,
            len(json_data["scenes"]),
        )

        # Verify scene 1 has multiple batches (since it has 55 lines with max_batch_size=5)
        scene1_batch_count = len(subtitles.scenes[0].batches)
        self.assertLoggedGreater(
            "scene 1 multiple batches",
            scene1_batch_count,
            1,
        )

        # Test event system with translation
        translation_provider = TranslationProvider.get_provider(options)
        translator = SubtitleTranslator(options, translation_provider)

        batch_events = []
        scene_events = []

        def on_batch_translated(_sender, batch):
            batch_events.append({
                'scene': batch.scene,
                'batch': batch.number,
                'size': batch.size,
                'summary': batch.summary
            })

        def on_scene_translated(_sender, scene):
            scene_events.append({
                'scene': scene.number,
                'summary': scene.summary,
                'linecount': scene.linecount,
                'batch_count': scene.size
            })

        # Subscribe to events
        translator.events.batch_translated.connect(on_batch_translated)
        translator.events.scene_translated.connect(on_scene_translated)

        # Execute translation
        translator.TranslateSubtitles(subtitles)

        # Verify events were fired
        self.assertLoggedEqual("batch events fired", actual_batch_count, len(batch_events))

        self.assertLoggedEqual("scene events fired", len(json_data["scenes"]), len(scene_events))

        # Verify event data accuracy
        for event in batch_events:
            self.assertLoggedGreater(
                f"batch event scene {event['scene']} size",
                event['size'],
                0,
            )

        for i, event in enumerate(scene_events):
            expected_scene_num = i + 1
            self.assertLoggedEqual(f"scene event {i} number", expected_scene_num, event['scene'])

            self.assertLoggedGreater(
                f"scene event {i} linecount",
                event['linecount'],
                0,
            )

        # Note: Translation may fail due to dummy provider limitations, but events should still fire
        # Just verify that we tried to translate (events fired properly)
        self.assertLoggedGreater(
            "translation attempted",
            len(batch_events),
            0,
        )

        self.assertLoggedGreater(
            "scene processing completed",
            len(scene_events),
            0,
        )

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

            self.assertLoggedEqual("explicit prompt used", explicit_prompt, options.get('prompt'))

            # Test without explicit prompt - should use instruction file
            options_no_prompt = init_options(
                provider="Dummy Provider",
                model="dummy-model",
                instruction_file=instruction_file_path
            )

            self.assertLoggedEqual(
                "instruction file prompt used",
                "Translate these subtitles from instruction file",
                options_no_prompt.get('prompt')
            )

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

        self.assertLoggedEqual("user modified prompt preserved", user_modified_prompt, translator.settings.get('prompt'))

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

            self.assertLoggedEqual("instruction file prompt", "Instruction file prompt", options.get('prompt'))

            self.assertLoggedEqual("instruction file instructions", "Instruction file instructions", options.get('instructions'))

            self.assertLoggedEqual("instruction file target_language", "French", options.get('target_language'))

            self.assertLoggedEqual("instruction file task_type", "CustomTask", options.get('task_type'))

        finally:
            if os.path.exists(instruction_file_path):
                os.remove(instruction_file_path)


if __name__ == '__main__':
    unittest.main()
