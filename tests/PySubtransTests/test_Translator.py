from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch

from PySubtrans.Helpers.ContextHelpers import GetBatchContext
from PySubtrans.Helpers.Parse import ParseNames
from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Translation import Translation
from PySubtrans.Helpers.SubtitleHelpers import FindBestSplitIndex
from PySubtrans.Helpers.TestCases import DummyProvider, PrepareSubtitles, SubtitleTestCase
from PySubtrans.Helpers.Tests import log_info, log_test_name
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleBatch import SubtitleBatch
from PySubtrans.SubtitleBatcher import SubtitleBatcher
from PySubtrans.SubtitleEditor import SubtitleEditor
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.SubtitleLine import SubtitleLine
from PySubtrans.Subtitles import Subtitles
from PySubtrans.SubtitleScene import SubtitleScene
from PySubtrans.SubtitleTranslator import SubtitleTranslator
from PySubtrans.TranslationEvents import TranslationEvents
from PySubtrans.TranslationParser import TranslationParser

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

    def test_ProcessTranslation_strips_unclosed_terminology_tag(self):
        """TranslationParser should strip a trailing unclosed terminology tag from the last line."""
        options = deepcopy(self.options)
        options.add('max_characters', 3)
        parser = TranslationParser(self.options.get_str('task_type') or "Translation", options)
        translation = Translation({
            'text': "#1\nOriginal>\nfoo\nTranslation>\nbar\n<terminology>foo::bar"
        })

        translated = parser.ProcessTranslation(translation)

        self.assertIsNotNone(translated)
        self.assertIsNotNone(parser.translated)
        self.assertEqual(parser.translated[-1].text, "bar")
        self.assertEqual(parser.errors, [])


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


class FindBestSplitIndexTests(SubtitleTestCase):
    def test_FindBestSplitIndex_picks_largest_gap(self):
        """FindBestSplitIndex should prefer the index with the largest time gap closest to the midpoint"""
        # 8 lines, uniform 1s timing/gaps EXCEPT a large gap (93s) between index 3 and 4 (the midpoint)
        lines = [SubtitleLine.Construct(i + 1, timedelta(seconds=i * 2), timedelta(seconds=i * 2 + 1), f"Line {i + 1}") for i in range(4)]
        lines.append(SubtitleLine.Construct(5, timedelta(seconds=100), timedelta(seconds=101), "Line 5"))
        lines += [SubtitleLine.Construct(i + 1, timedelta(seconds=100 + (i - 4) * 2), timedelta(seconds=100 + (i - 4) * 2 + 1), f"Line {i + 1}") for i in range(5, 8)]

        result = FindBestSplitIndex(lines)
        self.assertLoggedEqual("Split index at large gap", 4, result)

    def test_FindBestSplitIndex_too_small(self):
        """FindBestSplitIndex should return None when the list is too small to split"""
        single_line = [SubtitleLine.Construct(1, timedelta(seconds=0), timedelta(seconds=1), "Line 1")]
        self.assertLoggedIsNone("Single line returns None", FindBestSplitIndex(single_line))
        self.assertLoggedIsNone("Empty list returns None", FindBestSplitIndex([]))

    def test_FindBestSplitIndex_two_lines(self):
        """FindBestSplitIndex should return a valid split index for a 2-line list"""
        lines = [
            SubtitleLine.Construct(1, timedelta(seconds=0), timedelta(seconds=1), "Line 1"),
            SubtitleLine.Construct(2, timedelta(seconds=2), timedelta(seconds=3), "Line 2"),
        ]
        result = FindBestSplitIndex(lines)
        self.assertLoggedEqual("Two lines splits at index 1", 1, result)

    def test_FindBestSplitIndex_uniform_gaps_picks_midpoint(self):
        """With uniform gaps, FindBestSplitIndex should split at the midpoint (highest proximity score)"""
        # 8 lines with identical 1s gaps between every pair — proximity weighting picks the midpoint
        lines = [SubtitleLine.Construct(i + 1, timedelta(seconds=i * 2), timedelta(seconds=i * 2 + 1), f"Line {i + 1}") for i in range(8)]
        midpoint = len(lines) // 2  # 4
        result = FindBestSplitIndex(lines)
        self.assertLoggedEqual("Uniform gaps splits at midpoint", midpoint, result)

    def test_FindBestSplitIndex_off_center_gap_wins_when_large_enough(self):
        """An off-center gap should beat the midpoint only when it is large enough to overcome proximity weighting"""
        # 8 lines; midpoint is at index 4 (proximity 4) with a 1s gap.
        # Index 2 (proximity 2) has a 10s gap. Score at 4 = 4*1000 = 4000, score at 2 = 2*10000 = 20000.
        # Index 2 should win.
        lines = [SubtitleLine.Construct(i + 1, timedelta(seconds=i * 2), timedelta(seconds=i * 2 + 1), f"Line {i + 1}") for i in range(8)]
        # Place a 10s gap between lines[1] (end=3s) and lines[2] (start=13s)
        lines[2] = SubtitleLine.Construct(3, timedelta(seconds=13), timedelta(seconds=14), "Line 3")
        lines[3] = SubtitleLine.Construct(4, timedelta(seconds=15), timedelta(seconds=16), "Line 4")
        lines[4] = SubtitleLine.Construct(5, timedelta(seconds=17), timedelta(seconds=18), "Line 5")
        lines[5] = SubtitleLine.Construct(6, timedelta(seconds=19), timedelta(seconds=20), "Line 6")
        lines[6] = SubtitleLine.Construct(7, timedelta(seconds=21), timedelta(seconds=22), "Line 7")
        lines[7] = SubtitleLine.Construct(8, timedelta(seconds=23), timedelta(seconds=24), "Line 8")
        result = FindBestSplitIndex(lines)
        self.assertLoggedEqual("Large off-center gap beats midpoint", 2, result)


class SplitBatchTranslationTests(SubtitleTestCase):
    def __init__(self, methodName):
        super().__init__(methodName, custom_options={
            'max_batch_size': 100,
            'autosplit_on_error': True,
        })

    def setUp(self):
        super().setUp()
        provider = DummyProvider(data=chinese_dinner_data)
        self.originals = PrepareSubtitles(chinese_dinner_data, 'original')
        batcher = SubtitleBatcher(self.options)
        with SubtitleEditor(self.originals) as editor:
            editor.AutoBatch(batcher)
        self.translator = SubtitleTranslator(self.options, translation_provider=provider)
        scene_1 = self.originals.GetScene(1)
        if scene_1 is None:
            self.fail("Scene 1 not found in test data")
        batch_1 = scene_1.GetBatch(1)
        if batch_1 is None:
            self.fail("Batch 1 not found in scene 1")
        self.batch_1 : SubtitleBatch = batch_1
        self.context = GetBatchContext(self.originals, 1, 1)

    def test_TranslateSplitBatch_translates_all_lines(self):
        """_translate_split_batch should split the batch, translate each half, and merge all lines"""
        self.assertLoggedGreater("Batch has enough lines to split", len(self.batch_1.originals), 2)

        result = self.translator._translate_split_batch(self.batch_1, None, self.context)

        self.assertLoggedEqual("Returns True on success", True, result)
        self.assertLoggedEqual("All lines translated", len(self.batch_1.originals), len(self.batch_1.translated or []))
        self.assertLoggedEqual("No errors after split", 0, len(self.batch_1.errors or []))

    def test_TranslateSplitBatch_line_numbers_filtering(self):
        """_translate_split_batch should only include lines matching line_numbers when provided"""
        line_numbers = [line.number for line in self.batch_1.originals[:3]]

        result = self.translator._translate_split_batch(self.batch_1, line_numbers, self.context)

        self.assertLoggedEqual("Returns True", True, result)
        self.assertLoggedEqual("Only filtered lines in result", len(line_numbers), len(self.batch_1.translated or []))

    def test_TranslateSplitBatch_partial_failure_records_errors(self):
        """When one batch half fails to translate, errors are recorded but split still returns True"""
        call_count = [0]
        original_request = self.translator.client.RequestTranslation

        def fail_on_second_call(prompt, temperature=None, streaming_callback=None):
            call_count[0] += 1
            if call_count[0] == 2:
                return None
            return original_request(prompt, temperature, streaming_callback)

        with patch.object(self.translator.client, 'RequestTranslation', side_effect=fail_on_second_call):
            result = self.translator._translate_split_batch(self.batch_1, None, self.context)

        self.assertLoggedEqual("Returns True (split was attempted)", True, result)
        self.assertLoggedGreater("Errors recorded for failed half", len(self.batch_1.errors or []), 0)

    def test_split_triggered_when_errors_and_split_on_error(self):
        """TranslateBatch should call _translate_split_batch when batch has errors and split_on_error is True"""
        original_process = self.translator.ProcessBatchTranslation

        def inject_errors(batch, translation, line_numbers=None):
            original_process(batch, translation, line_numbers)
            batch.errors = [SubtitleError("Injected test error")]

        with patch.object(self.translator, 'ProcessBatchTranslation', side_effect=inject_errors):
            with patch.object(self.translator, '_translate_split_batch', return_value=True) as mock_split:
                self.translator.TranslateBatch(self.batch_1, None, self.context)

        self.assertLoggedGreater("Split was triggered by batch errors", mock_split.call_count, 0)

    def test_split_not_triggered_when_split_on_error_disabled(self):
        """TranslateBatch should not call _translate_split_batch when split_on_error is False"""
        options = deepcopy(self.options)
        options.add('autosplit_on_error', False)
        provider = DummyProvider(data=chinese_dinner_data)
        translator = SubtitleTranslator(options, translation_provider=provider)

        original_process = translator.ProcessBatchTranslation

        def inject_errors(batch, translation, line_numbers=None):
            original_process(batch, translation, line_numbers)
            batch.errors = [SubtitleError("Injected test error")]

        with patch.object(translator, 'ProcessBatchTranslation', side_effect=inject_errors):
            with patch.object(translator, '_translate_split_batch') as mock_split:
                translator.TranslateBatch(self.batch_1, None, self.context)

        self.assertLoggedEqual("Split not triggered when disabled", 0, mock_split.call_count)

    def test_split_suppresses_retry_on_error(self):
        """When split_on_error fires successfully, retry_on_error should not also be triggered"""
        options = deepcopy(self.options)
        options.add('retry_on_error', True)
        provider = DummyProvider(data=chinese_dinner_data)
        translator = SubtitleTranslator(options, translation_provider=provider)

        original_process = translator.ProcessBatchTranslation

        def inject_errors(batch, translation, line_numbers=None):
            original_process(batch, translation, line_numbers)
            batch.errors = [SubtitleError("Injected test error")]

        with patch.object(translator, 'ProcessBatchTranslation', side_effect=inject_errors):
            with patch.object(translator, '_translate_split_batch', return_value=True):
                with patch.object(translator, 'RequestRetranslation') as mock_retry:
                    translator.TranslateBatch(self.batch_1, None, self.context)

        self.assertLoggedEqual("Retry not triggered when split succeeded", 0, mock_retry.call_count)


class TerminologyMapParsingTests(LoggedTestCase):
    """Tests for Translation.terminology property and <terminology> tag extraction"""

    parse_cases = [
        (
            "Line 1\nLine 2\n<terminology>Dragon::Drache\nHero::Held</terminology>",
            {"Dragon": "Drache", "Hero": "Held"},
        ),
        (
            "<terminology>Knight::Ritter</terminology>\nTranslation text here",
            {"Knight": "Ritter"},
        ),
        (
            "Just plain translation text with no tag",
            None,
        ),
        (
            "<terminology>MissingSeparator</terminology>\nSome text",
            None,
        ),
        (
            "<terminology>Key::Value::Extra</terminology>",
            {"Key": "Value::Extra"},
        ),
        (
            "<terminology></terminology>",
            None,
        ),
    ]

    def test_terminology_property(self):
        for text, expected in self.parse_cases:
            with self.subTest(text=text[:50]):
                translation = Translation({'text': text})
                self.assertLoggedEqual("terminology dict", expected, translation.terminology, input_value=text)

    def test_terminology_tag_stripped_from_text(self):
        text = "Line 1\nLine 2\n<terminology>Dragon::Drache</terminology>"
        translation = Translation({'text': text})
        self.assertLoggedIsNotNone("translation text present", translation.text)
        if translation.text:
            self.assertLoggedNotIn("terminology tag absent from text", "<terminology>", translation.text)

    def test_terminology_is_none_without_tag(self):
        translation = Translation({'text': "Just some translation text"})
        self.assertLoggedIsNone("no terminology when tag absent", translation.terminology)


class TerminologyMapContextTests(SubtitleTestCase):
    """Tests that SubtitleTranslator injects terminology into batch context"""

    def __init__(self, methodName):
        super().__init__(methodName, custom_options={
            'max_batch_size': 100,
            'build_terminology_map': True,
        })

    def _setup(self, terminology_map : dict|None = None) -> tuple[Subtitles, SubtitleTranslator]:
        provider = DummyProvider(data=chinese_dinner_data)
        originals = PrepareSubtitles(chinese_dinner_data, 'original')
        batcher = SubtitleBatcher(self.options)
        with SubtitleEditor(originals) as editor:
            editor.AutoBatch(batcher)
        translator = SubtitleTranslator(self.options, translation_provider=provider, terminology_map=terminology_map)
        return originals, translator

    def _translate_and_capture_context(self, translator : SubtitleTranslator, originals : Subtitles) -> dict:
        captured : dict = {}
        def on_batch_translated(_sender, batch):
            captured.update(batch.context)
        translator.events.batch_translated.connect(on_batch_translated)
        scene = originals.GetScene(1)
        translator.TranslateScene(originals, scene, batch_numbers=[1])
        return captured

    def test_terminology_injected_into_batch_context(self):
        """Translator injects terminology into batch context when map is populated"""
        terminology_map = {"Dragon": "Drache", "Hero": "Held"}
        originals, translator = self._setup(terminology_map)

        context = self._translate_and_capture_context(translator, originals)

        self.assertLoggedIn("terminology key present", 'terminology', context)
        terminology = context.get('terminology', '')
        self.assertLoggedIn("Dragon entry in terminology", "Dragon::Drache", terminology)
        self.assertLoggedIn("Hero entry in terminology", "Hero::Held", terminology)

    def test_terminology_absent_when_map_not_set(self):
        """Translator does not inject terminology when no map was provided"""
        originals, translator = self._setup()

        context = self._translate_and_capture_context(translator, originals)

        self.assertLoggedNotIn("terminology key absent", 'terminology', context)

    def test_terminology_absent_when_map_empty(self):
        """Translator does not inject terminology when map is an empty dict"""
        originals, translator = self._setup(terminology_map={})

        context = self._translate_and_capture_context(translator, originals)

        self.assertLoggedNotIn("terminology key absent for empty map", 'terminology', context)


class TerminologyMapAccumulationTests(SubtitleTestCase):
    """Tests for SubtitleTranslator accumulating terminology into translator.terminology_map"""

    def __init__(self, methodName):
        super().__init__(methodName, custom_options={
            'max_batch_size': 100,
            'build_terminology_map': True,
        })

    def _make_data_with_terminology(self, batch_key : str, terminology : dict) -> dict:
        """Return a copy of chinese_dinner_data with a <terminology> block appended to one batch response"""
        term_block = '\n<terminology>' + '\n'.join(f"{k}::{v}" for k, v in terminology.items()) + '</terminology>'
        data = SettingsType(chinese_dinner_data)
        response_map = data.get_dict('response_map')
        response_map.add(batch_key, (response_map.get_str(batch_key) or '') + term_block)
        return data

    def _setup(self, data : dict, seed : dict[str,str]|None = None) -> tuple[Subtitles, SubtitleTranslator]:
        provider = DummyProvider(data=data)
        originals = PrepareSubtitles(data, 'original')
        batcher = SubtitleBatcher(self.options)
        with SubtitleEditor(originals) as editor:
            editor.AutoBatch(batcher)
        translator = SubtitleTranslator(self.options, translation_provider=provider, terminology_map=seed)
        return originals, translator

    def test_terminology_accumulated_after_batch(self):
        """TranslateScene merges returned terminology into translator.terminology_map"""
        # Terms must appear in the actual batch content to pass content validation.
        # 星野 appears in the Japanese originals; Hoshino and meal appear in the translations.
        expected = {"星野": "Hoshino", "食事": "meal"}
        data = self._make_data_with_terminology('Translate scene 1 batch 1', expected)
        originals, translator = self._setup(data)

        scene = originals.GetScene(1)
        self.assertLoggedIsNotNone("Scene 1 exists", scene)
        if not scene:
            return

        translator.TranslateScene(originals, scene, batch_numbers=[1])

        terminology_map = translator.terminology_map
        self.assertLoggedIsInstance("terminology_map is a dict", terminology_map, dict)
        for term, translation in expected.items():
            self.assertLoggedIn(f"term '{term}' present", term, terminology_map)
            self.assertLoggedEqual(f"translation for '{term}'", translation, terminology_map.get(term))

    def test_terminology_first_seen_wins(self):
        """Pre-existing terminology entries are not overwritten (first-seen-wins)"""
        expected = {"星野": "Hoshino", "食事": "meal"}
        data = self._make_data_with_terminology('Translate scene 1 batch 1', expected)
        originals, translator = self._setup(data, seed={"星野": "Hoseki"})

        scene = originals.GetScene(1)
        self.assertLoggedIsNotNone("Scene 1 exists", scene)
        if not scene:
            return

        translator.TranslateScene(originals, scene, batch_numbers=[1])

        terminology_map = translator.terminology_map
        self.assertLoggedEqual("星野 keeps first translation", "Hoseki", terminology_map.get("星野"))
        self.assertLoggedIn("食事 was added", "食事", terminology_map)

    def test_no_accumulation_when_disabled(self):
        """Terminology is not accumulated when build_terminology_map is False"""
        expected = {"星野": "Hoshino"}
        data = self._make_data_with_terminology('Translate scene 1 batch 1', expected)

        options = deepcopy(self.options)
        options.add('build_terminology_map', False)
        provider = DummyProvider(data=data)
        originals = PrepareSubtitles(data, 'original')
        batcher = SubtitleBatcher(options)
        with SubtitleEditor(originals) as editor:
            editor.AutoBatch(batcher)
        translator = SubtitleTranslator(options, translation_provider=provider)

        scene = originals.GetScene(1)
        self.assertLoggedIsNotNone("Scene 1 exists", scene)
        if not scene:
            return

        translator.TranslateScene(originals, scene, batch_numbers=[1])

        self.assertLoggedTrue("terminology_map not populated", not translator.terminology_map)

    def test_identity_mappings_are_ignored(self):
        """Identity terminology pairs (left == right) are ignored and never stored."""
        terms = {
            "食事": "食事",      # identity in source language
            "Hoshino": "Hoshino", # identity in target language
            "星野": "Hoshino",   # valid non-identity pair
        }
        data = self._make_data_with_terminology('Translate scene 1 batch 1', terms)
        originals, translator = self._setup(data)

        scene = originals.GetScene(1)
        self.assertLoggedIsNotNone("Scene 1 exists", scene)
        if not scene:
            return

        translator.TranslateScene(originals, scene, batch_numbers=[1])

        terminology_map = translator.terminology_map
        self.assertLoggedNotIn("source-language identity not stored", "食事", terminology_map)
        self.assertLoggedNotIn("target-language identity not stored", "Hoshino", terminology_map)
        self.assertLoggedIn("non-identity term stored", "星野", terminology_map)
        self.assertLoggedEqual("non-identity translation stored", "Hoshino", terminology_map.get("星野"))

    def test_reverse_mappings_are_corrected(self):
        """Reversed pairs are auto-corrected using batch content; if the corrected pair already exists it is deduplicated."""
        terms = {
            "Hoshino": "星野",  # reversed — model put translation as key
            "食事": "meal",     # correctly oriented
        }
        data = self._make_data_with_terminology('Translate scene 1 batch 1', terms)
        originals, translator = self._setup(data, seed={"星野": "Hoshino"})

        scene = originals.GetScene(1)
        self.assertLoggedIsNotNone("Scene 1 exists", scene)
        if not scene:
            return

        translator.TranslateScene(originals, scene, batch_numbers=[1])

        terminology_map = translator.terminology_map
        self.assertLoggedEqual("existing mapping preserved", "Hoshino", terminology_map.get("星野"))
        self.assertLoggedNotIn("reversed key not added as new entry", "Hoshino", terminology_map)
        self.assertLoggedIn("correctly oriented term added", "食事", terminology_map)
        self.assertLoggedEqual("correctly oriented term value", "meal", terminology_map.get("食事"))

    def test_terminology_accumulated_after_split_retranslation(self):
        """Terminology returned by split half-translations is merged into the shared terminology map."""
        options = deepcopy(self.options)
        options.add('autosplit_on_error', True)
        provider = DummyProvider(data=chinese_dinner_data)
        originals = PrepareSubtitles(chinese_dinner_data, 'original')
        batcher = SubtitleBatcher(options)
        with SubtitleEditor(originals) as editor:
            editor.AutoBatch(batcher)
        translator = SubtitleTranslator(options, translation_provider=provider)

        scene = originals.GetScene(1)
        self.assertLoggedIsNotNone("Scene 1 exists", scene)
        if not scene:
            return

        original_process = translator.ProcessBatchTranslation
        process_call_count = 0

        def inject_initial_error(batch, translation, line_numbers=None):
            nonlocal process_call_count
            process_call_count += 1
            original_process(batch, translation, line_numbers)
            if process_call_count == 1:
                batch.errors = [SubtitleError("Injected test error to force split")]

        original_request = translator.client.RequestTranslation
        request_call_count = 0

        def request_with_split_terminology(prompt, temperature=None, streaming_callback=None):
            nonlocal request_call_count
            request_call_count += 1
            translation = original_request(prompt, temperature, streaming_callback)
            if not translation:
                return None

            full_text = translation.full_text or translation.text or ""
            if request_call_count == 2:
                full_text += "\n<terminology>星野::Hoshino</terminology>"
            elif request_call_count == 3:
                full_text += "\n<terminology>食事::meal</terminology>"
            return Translation({'text': full_text})

        with patch.object(translator, 'ProcessBatchTranslation', side_effect=inject_initial_error):
            with patch.object(translator.client, 'RequestTranslation', side_effect=request_with_split_terminology):
                translator.TranslateScene(originals, scene, batch_numbers=[1])

        terminology_map = translator.terminology_map
        self.assertLoggedEqual("split learned 星野 mapping", "Hoshino", terminology_map.get("星野"))
        self.assertLoggedEqual("split learned 食事 mapping", "meal", terminology_map.get("食事"))


