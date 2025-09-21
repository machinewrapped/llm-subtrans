import os
import tempfile
import unittest

from PySubtrans import (
    batch_subtitles,
    init_options,
    init_project,
    init_subtitles,
    init_translator,
)
from PySubtrans.Helpers.TestCases import DummyProvider  # noqa: F401 - ensure provider is registered
from PySubtrans.Helpers.Tests import (
    log_input_expected_error,
    log_input_expected_result,
    log_test_name,
    skip_if_debugger_attached,
)
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import TranslationImpossibleError


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

            log_input_expected_result("translator initialised", True, project.translator is not None)
            self.assertIsNotNone(project.translator)
        finally:
            if os.path.exists(subtitle_path):
                os.remove(subtitle_path)


if __name__ == '__main__':
    unittest.main()
