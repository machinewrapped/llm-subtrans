import unittest
import regex

from PySubtrans.Helpers.Tests import log_input_expected_result, log_test_name
from PySubtrans.Helpers.Text import (
    EnsureFullWidthPunctuation,
    break_sequences,
    standard_filler_words,
    BreakDialogOnOneLine,
    BreakLongLine,
    CompileDialogSplitPattern,
    CompileFillerWordsPattern,
    ContainsTags,
    ExtractTag,
    ExtractTagList,
    IsTextContentEqual,
    LimitTextLength,
    Linearise,
    NormaliseDialogTags,
    RemoveFillerWords,
    RemoveWhitespaceAndPunctuation,
    SanitiseSummary
    )

class TestTextHelpers(unittest.TestCase):
    dialog_marker = "- "

    linearise_cases = [
        ("This is a test", "This is a test"),
        (["This is a test", "I hope it passes"], "This is a test | I hope it passes"),
        (["This is a test", "I hope it passes", "I really do"], "This is a test | I hope it passes | I really do"),
        ([20, 30, 40], "20 | 30 | 40"),
    ]

    def test_Linearise(self):
        log_test_name("Linearise")
        for input, expected in self.linearise_cases:
            with self.subTest():
                result = Linearise(input)
                log_input_expected_result(str(input), expected, result)
                self.assertEqual(result, expected)

    remove_whitespace_and_punctuation_cases = [
        ("This is a test", "Thisisatest"),
        ("This\nis\na\ntest", "Thisisatest"),
        ("This, is a test!", "Thisisatest"),
    ]

    def test_RemoveWhitespaceAndPunctuation(self):
        log_test_name("RemoveWhitespaceAndPunctuation")
        for text, expected in self.remove_whitespace_and_punctuation_cases:
            with self.subTest(text=text):
                result = RemoveWhitespaceAndPunctuation(text)
                log_input_expected_result(text, expected, result)
                self.assertEqual(result, expected)

    is_text_content_equal_cases = [
        ("This is a test", "This is a test", True),
        ("This is a test", "This is a test!", True),
        ("This is a test", "Thisisatest\n", True),
        ("This!is!a!test", "This is a test", True),
        ("This is a test", "This\nis\na\ntest", True),
        ("This is a test", "This is not a test", False),
        ("This is a test", "This\nis\nnot\na\ntest", False),
    ]

    def test_IsTextContentEqual(self):
        log_test_name("IsTextContentEqual")
        for text1, text2, expected in self.is_text_content_equal_cases:
            with self.subTest(text1=text1, text2=text2):
                result = IsTextContentEqual(text1, text2)
                log_input_expected_result([text1, text2], expected, result)
                self.assertEqual(result, expected)

    normalise_tags_cases = {
        "This is a test": "This is a test",
        "- This is a test": "This is a test",
        "- This is a test\n- I also think that": "- This is a test\n- I also think that",
        "This is a test\n- I also think that": "- This is a test\n- I also think that",
        "- This is a test\nI also think that": "- This is a test\n- I also think that",
        "- This is a test - a harder one\n- I hope it passes": "- This is a test - a harder one\n- I hope it passes",
        "- This is a test - a harder one\nI hope it passes": "- This is a test - a harder one\n- I hope it passes"
    }

    def test_NormaliseDialogTags(self):
        log_test_name("NormaliseDialogTags")
        for text, expected in self.normalise_tags_cases.items():
            with self.subTest(text=text):
                result = NormaliseDialogTags(text, self.dialog_marker)
                log_input_expected_result(text, expected, result)
                self.assertEqual(result, expected)

    break_dialog_on_one_line_cases = {
        "This is a test": "This is a test",
        "This is a test... - This should be on another line": "This is a test...\n- This should be on another line",
        "This is a test - it shouldn't break this one": "This is a test - it shouldn't break this one",
        "- This is a test\n- I also think that": "- This is a test\n- I also think that",
        "This is a test! - A hard one! - I hope it passes": "This is a test!\n- A hard one!\n- I hope it passes",
        "- This is a test! - Another hard one! - I hope it passes": "- This is a test!\n- Another hard one!\n- I hope it passes",
    }

    def test_BreakDialogOnOneLine(self):
        log_test_name("BreakDialogOnOneLine")
        compiled_pattern = CompileDialogSplitPattern(self.dialog_marker)
        for text, expected in self.break_dialog_on_one_line_cases.items():
            with self.subTest(text=text):
                result = BreakDialogOnOneLine(text, self.dialog_marker)
                log_input_expected_result(text, expected, result)
                self.assertEqual(result, expected)

                compiled_result = BreakDialogOnOneLine(text, compiled_pattern)
                log_input_expected_result(text, expected, compiled_result)
                self.assertEqual(compiled_result, expected)

    break_long_line_cases = [
        ("This is a test", 100, 10, "This is a test"),
        ("This is a test", 10, 4, "This is\na test"),
        ("This is a test with punctuation. It should break at the punctuation.", 42, 4, "This is a test with punctuation.\nIt should break at the punctuation."),
        ("Where will this line break? It should break at the question mark.", 42, 4, "Where will this line break?\nIt should break at the question mark."),
        ("This line should break at the comma, not at a space.", 42, 4, "This line should break at the comma,\nnot at a space."),
        ("A parenthetical (which should be kept together).", 42, 10, "A parenthetical\n(which should be kept together)."),
        ("A line with a \"Quote that should not be broken.\"", 42, 10, "A line with a\n\"Quote that should not be broken.\""),
        ("Break at the exclamation! Don't break here, because commas are lower priority.", 55, 4, "Break at the exclamation!\nDon't break here, because commas are lower priority."),
        ("This line already has line breaks.\nWe should respect them.", 20, 4, "This line already has line breaks.\nWe should respect them."),
        ("This line has punctuation and quite uneven line lengths. Break it.", 60, 4, "This line has punctuation and quite uneven line lengths.\nBreak it."),
        ("This line has punctuation and quite uneven line lengths. Break it.", 60, 12, "This line has punctuation and\nquite uneven line lengths. Break it."),
        ("A line with a <i>block of italics that should not be broken.</i>", 60, 10, "A line with a\n<i>block of italics that should not be broken.</i>"),
        ("We shouldn't split the number 500,000 even if it's a good position", 60, 10, "We shouldn't split the number\n500,000 even if it's a good position"),
        ("Break this! But not at the exclamation mark because it would be too unbalanced.", 45, 35, "Break this! But not at the exclamation\nmark because it would be too unbalanced."),
    ]

    def test_BreakLongLines(self):
        log_test_name("BreakLongLines")
        break_patterns = [regex.compile(sequence) for sequence in break_sequences]

        for text, max_length, min_length, expected in self.break_long_line_cases:
            with self.subTest(text=text):
                result = BreakLongLine(text, max_length, min_length, break_patterns)
                log_input_expected_result((text, max_length, min_length), expected, result)
                self.assertEqual(result, expected)

    limit_text_length_cases = [
        # input is shorter than max_length
        ("This is just a short string", 100, "This is just a short string"),
        ("First sentence. Second sentence can fit too.", 100, "First sentence. Second sentence can fit too."),
        # input is exactly at max_length
        ("Welcome home!", 13, "Welcome home!"),
        ("This is exactly thirty-nine characters.", 39, "This is exactly thirty-nine characters."),
        # input is longer than max_length
        ("This is a sentence. This is too long.", 18, "This is a sentence."),
        ("First sentence. Second sentence is too long to fit.", 31, "First sentence."),
        ("Hello! How are you doing today? I hope well.", 32, "Hello! How are you doing today?"),
        ("This is a very very long sentence without a proper end", 10, "This is a..."),
        ("VeryLongWordWithoutAnyBreaks", 10, "VeryLongWo..."),
    ]

    def test_LimitTextLength(self):
        log_test_name("LimitTextLength")
        for text, limit, expected in self.limit_text_length_cases:
            with self.subTest(text=text):
                result = LimitTextLength(text, limit)
                log_input_expected_result(text, expected, result)
                self.assertEqual(result, expected)

    contains_tags_cases = [
        ("This is a test", False),
        ("This is a test with a trap -> right here", False),
        ("This is a trap! < Did you fall for it?", False),
        ("<i>Test with tags</i>", True),
        ("This is a <b>test</b>", True),
        ("This is a <i>test</i>", True),
        ("This is a <b>test</b> with <i>tags</i>", True),
        ("<b>Test</b> with <i>tags</i>", True),
        ("<b>Test</b> with tags", True),
        ("Test with <i>tags</i>", True),
    ]

    def test_ContainsTags(self):
        log_test_name("ContainsTags")
        for text, expected in self.contains_tags_cases:
            with self.subTest(text=text):
                result = ContainsTags(text)
                log_input_expected_result(text, expected, result)
                self.assertEqual(result, expected)

    extract_tag_cases = [
        ("This test has no tags", "tag", ("This test has no tags", None)),
        ("This test has a <tag>tagged section</tag>", "tag", ("This test has a", "tagged section")),
        ("This is the first line.\n<second>The second line is a tag</second>\n", "second", ("This is the first line.", "The second line is a tag")),
        ("This is the first line.\n<second>The second line is a tag</second>\nThe third line follows on.", "second", ("This is the first line.\nThe third line follows on.", "The second line is a tag")),
        ("This is the first line.\nThis is the second line.\n<third>The third line is a tag</third>\n", "third", ("This is the first line.\nThis is the second line.", "The third line is a tag")),
    ]

    def test_ExtractTag(self):
        log_test_name("ExtractTag")
        for text, tagname, expected in self.extract_tag_cases:
            with self.subTest(text=text):
                result = ExtractTag(tagname, text)
                log_input_expected_result(text, expected, result)
                self.assertEqual(result, expected)

    extract_taglist_cases = [
        ("This test has no tags", "tag", ("This test has no tags", [])),
        ("This test has a <tag>tagged section</tag>", "tag", ("This test has a", ["tagged section"])),
        ("This test has a <tag>tagged, list, of, words</tag>", "tag", ("This test has a", ["tagged", "list", "of", "words"])),
        ("This is the first line.\n<list>Item 1\nItem 2\nItem 3</list>\nThis is the next line.", "list", ("This is the first line.\nThis is the next line.", ["Item 1", "Item 2", "Item 3"])),
    ]

    def test_ExtractTaglist(self):
        log_test_name("ExtractTaglist")
        for text, tagname, expected in self.extract_taglist_cases:
            with self.subTest(text=text):
                result = ExtractTagList(tagname, text)
                log_input_expected_result(text, expected, result)
                self.assertEqual(result, expected)

    sanitise_summary_cases = [
        ("", None, None, None),
        ("Summary of the batch - This is a summary", None, None, "This is a summary"),
        ("Movie Name: Summary of the scene - This is a summary", "Movie Name", None, "This is a summary"),
        ("Movie Name: Summary of the scene - This is a summary", "Movie Name", 10, "This is a..."),
        ("Scene 1: This is the first scene of Movie Name", "Movie Name", None, "This is the first scene of Movie Name"),
        ("An example of a summary with too much whitespace    ", None, None, "An example of a summary with too much whitespace"),
    ]

    def test_SanitiseSummary(self):
        log_test_name("SanitiseSummary")
        for text, movie_name, max_length, expected in self.sanitise_summary_cases:
            with self.subTest(text=text):
                result = SanitiseSummary(text, movie_name, max_length)
                log_input_expected_result(text, expected, result)
                self.assertEqual(result, expected)

    remove_filler_cases = [
        ("This is a normal sentence", "This is a normal sentence"),
        ("This is, err, not a normal sentence", "This is not a normal sentence"),
        ("Umm, this sentence has a filler word", "This sentence has a filler word"),
        ("This, err, sentence is, umm, full of filler words, eh?", "This sentence is full of filler words"),
        ("This sentence has no filler. Ah, but this one does.", "This sentence has no filler. But this one does.")
    ]

    def test_RemoveFillerWords(self):
        log_test_name("RemoveFillerWords")
        filler_patterns = CompileFillerWordsPattern(standard_filler_words)
        if not filler_patterns:
            log_input_expected_result("Filler patterns", "list", filler_patterns)
            return

        for text, expected in self.remove_filler_cases:
            with self.subTest(text=text):
                result = RemoveFillerWords(text, filler_patterns)
                log_input_expected_result(text, expected, result)
                self.assertEqual(result, expected)

    fullwidth_punctuation_cases = [
        ("你好,世界!", "你好，世界!"),
        ("一来拜寿,二来送终.", "一来拜寿，二来送终."),
        ("こんにちは、世界! こんにちは世界.", "こんにちは、世界! こんにちは世界."),
        ("안녕하세요,세계? 你好,世界! こんにちは、世界!", "안녕하세요，세계? 你好，世界! こんにちは、世界!"),
        ("Hello, world! 你好,世界!", "Hello, world! 你好，世界!"),
        ("안녕하세요. Hello, world! 你好,世界!", "안녕하세요. Hello, world! 你好，世界!"),
        ("これは、テストです.", "これは、テストです."),
        ("数学,物理,化学,生物.", "数学，物理，化学，生物."),
        ("没问题！这很容易。", "没问题！这很容易。"),
        ("시작하자:게임을 시작하자!", "시작하자：게임을 시작하자!")
    ]

    def test_EnsureFullWidthPunctuation(self):
        log_test_name("EnsureFullWidthPunctuation")
        for text, expected in self.fullwidth_punctuation_cases:
            with self.subTest(text=text):
                result = EnsureFullWidthPunctuation(text)
                log_input_expected_result(text, expected, result)
                self.assertEqual(result, expected)

if __name__ == '__main__':
    unittest.main()