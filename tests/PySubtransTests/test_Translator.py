from copy import deepcopy

from PySubtrans.Helpers.Parse import ParseNames
from PySubtrans.Helpers.TestCases import DummyProvider, PrepareSubtitles, SubtitleTestCase
from PySubtrans.Helpers.Tests import log_info, log_test_name
from PySubtrans.SubtitleBatch import SubtitleBatch
from PySubtrans.SubtitleBatcher import SubtitleBatcher
from PySubtrans.SubtitleEditor import SubtitleEditor
from PySubtrans.Subtitles import Subtitles
from PySubtrans.SubtitleScene import SubtitleScene
from PySubtrans.SubtitleTranslator import SubtitleTranslator
from PySubtrans.TranslationEvents import TranslationEvents

from ..TestData.chinese_dinner import chinese_dinner_data

class SubtitleTranslatorTests(SubtitleTestCase):
    def __init__(self, methodName):
        super().__init__(methodName, custom_options={
            'max_batch_size': 100,
        })

    def test_SubtitleTranslator(self):

        test_data = [ chinese_dinner_data ]

        for data in test_data:
            log_test_name(f"Testing translation of {data.get('movie_name')}")

            provider = DummyProvider(data=data)

            originals : Subtitles = PrepareSubtitles(data, 'original')
            reference : Subtitles = PrepareSubtitles(data, 'translated')

            self.assertEqual(originals.linecount, reference.linecount)

            batcher = SubtitleBatcher(self.options)
            with SubtitleEditor(originals) as editor:
                editor.AutoBatch(batcher)
            with SubtitleEditor(reference) as editor:
                editor.AutoBatch(batcher)

            self.assertEqual(len(originals.scenes), len(reference.scenes))

            for i in range(len(originals.scenes)):
                self.assertEqual(originals.scenes[i].size, reference.scenes[i].size)
                self.assertEqual(originals.scenes[i].linecount, reference.scenes[i].linecount)

            translator = SubtitleTranslator(self.options, translation_provider=provider)
            translator.events.batch_translated.connect(
                lambda sender, batch, original=originals, reference=reference: self.validate_batch(batch, original=original, reference=reference),
            )
            translator.events.scene_translated.connect(
                lambda sender, scene, original=originals, reference=reference: self.validate_scene(scene, original=original, reference=reference),
            )

            translator.TranslateSubtitles(originals)

    def validate_batch(self, batch : SubtitleBatch, original : Subtitles, reference : Subtitles):
        log_info(f"Validating scene {batch.scene} batch {batch.number}")
        log_info(f"Summary: {batch.summary}")
        self.assertIsNotNone(batch.summary)

        log_info(f"Scene: {batch.context.get('scene')}")
        self.assertIsNotNone(batch.context.get('scene'))

        self.assertEqual(batch.context.get('movie_name'), original.settings.get_str('movie_name'))
        self.assertEqual(batch.context.get('description'), original.settings.get_str('description'))
        batch_names = ParseNames(batch.context.get('names'))
        original_names = ParseNames(original.settings.get('names'))
        self.assertSequenceEqual(batch_names, original_names)

        reference_batch = reference.GetBatch(batch.scene, batch.number)

        self.assertLoggedEqual("Line count", reference_batch.size, batch.size)
        
        self.assertEqual(batch.first_line_number, reference_batch.first_line_number)
        self.assertEqual(batch.last_line_number, reference_batch.last_line_number)
        self.assertEqual(batch.start, reference_batch.start)
        self.assertEqual(batch.end, reference_batch.end)

        original_batch = original.GetBatch(batch.scene, batch.number)
        for i in range(len(batch.originals)):
            self.assertEqual(original_batch.originals[i], batch.originals[i])
            self.assertEqual(reference_batch.originals[i], batch.translated[i])

    def validate_scene(self, scene : SubtitleScene, original : Subtitles, reference : Subtitles):
        log_info(f"Validating scene {scene.number}")
        log_info(f"Summary: {scene.summary}")
        self.assertIsNotNone(scene.summary)

        reference_scene = reference.GetScene(scene.number)
        self.assertLoggedEqual("Batch count", reference_scene.size, scene.size)
        self.assertLoggedEqual("Line count", reference_scene.linecount, scene.linecount)


    def test_PostProcessTranslation(self):

        test_data = [ chinese_dinner_data ]

        for data in test_data:
            log_test_name(f"Testing translation of {data.get('movie_name')}")

            provider = DummyProvider(data=data)

            originals : Subtitles = PrepareSubtitles(data, 'original')
            reference : Subtitles = PrepareSubtitles(data, 'translated')

            self.assertEqual(originals.linecount, reference.linecount)

            batcher = SubtitleBatcher(self.options)
            with SubtitleEditor(originals) as editor:
                editor.AutoBatch(batcher)
            with SubtitleEditor(reference) as editor:
                editor.AutoBatch(batcher)

            self.assertEqual(len(originals.scenes), len(reference.scenes))

            options = deepcopy(self.options)
            options.add('postprocess_translation', True)
            translator = SubtitleTranslator(options, translation_provider=provider)
            translator.TranslateSubtitles(originals)

            self.assertIsNotNone(reference.originals)
            self.assertIsNotNone(originals.originals)
            self.assertIsNotNone(originals.translated)

            if not reference.originals or not originals.originals or not originals.translated:
                raise Exception("No subtitles to compare")

            differences = sum(1 if reference.originals[i] != originals.translated[i] else 0 for i in range(len(originals.originals)))
            unchanged = sum (1 if reference.originals[i] == originals.translated[i] else 0 for i in range(len(originals.originals)))

            expected_differences = data['expected_postprocess_differences']
            expected_unchanged = data['expected_postprocess_unchanged']

            self.assertLoggedEqual("Differences", expected_differences, differences)

            self.assertLoggedEqual("Unchanged", expected_unchanged, unchanged)


class TranslationEventsTests(SubtitleTestCase):
    def test_default_loggers_connection(self):
        """Test that default loggers can be connected and disconnected without errors"""
        events = TranslationEvents()

        # Verify connect/disconnect doesn't raise exceptions
        try:
            events.connect_default_loggers()
            events.disconnect_default_loggers()
        except Exception as e:
            self.fail(f"Default logger connection raised an exception: {e}")

    def test_custom_logger_connection(self):
        """Test that custom logger receives signals with keyword arguments"""
        events = TranslationEvents()

        # Track messages received by custom logger
        received_messages = []

        class TestLogger:
            def error(self, msg : str, *args, **kwargs):
                received_messages.append(('ERROR', msg))

            def warning(self, msg : str, *args, **kwargs):
                received_messages.append(('WARNING', msg))

            def info(self, msg : str, *args, **kwargs):
                received_messages.append(('INFO', msg))

        logger = TestLogger()

        # Connect and emit signals
        events.connect_logger(logger) #type: ignore
        events.error.send(self, message="Test error")
        events.warning.send(self, message="Test warning")
        events.info.send(self, message="Test info")

        # Verify signals were received correctly
        self.assertLoggedEqual("Messages received", 3, len(received_messages))
        self.assertLoggedEqual("Error message", "Test error", received_messages[0][1])
        self.assertLoggedEqual("Warning message", "Test warning", received_messages[1][1])
        self.assertLoggedEqual("Info message", "Test info", received_messages[2][1])


