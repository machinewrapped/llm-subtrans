from GuiSubtrans.GuiHelpers import GetDisplayLength, GetWrapKey, WrapKeyDominates
from GuiSubtrans.ViewModel.LineItem import LineItem
from PySubtrans.Helpers.TestCases import LoggedTestCase


class GetWrapKeyTests(LoggedTestCase):
    """Tests for the key used to cache subtitle row sizes."""

    def test_empty_text(self) -> None:
        self.assertLoggedEqual("empty text key", (), GetWrapKey(""))

    def test_rounds_each_line_up(self) -> None:
        text = "x" * 45 + "\n" + "x" * 50
        self.assertLoggedEqual("line lengths rounded up to 10", (5, 5), GetWrapKey(text), input_value=text)

    def test_distinguishes_line_lengths_with_same_total(self) -> None:
        balanced = "x" * 45 + "\n" + "x" * 47
        unbalanced = "x" * 10 + "\n" + "x" * 82
        self.assertLoggedTrue("same total length, different wrapping", GetWrapKey(balanced) != GetWrapKey(unbalanced))

    def test_distinguishes_line_count(self) -> None:
        self.assertLoggedTrue("extra line changes key", GetWrapKey("abc\ndef") != GetWrapKey("abc\ndef\nghi"))

    def test_ignores_line_order(self) -> None:
        self.assertLoggedEqual("line order does not matter", GetWrapKey("short\n" + "x" * 50), GetWrapKey("x" * 50 + "\nshort"))

    def test_counts_east_asian_characters_double(self) -> None:
        text = "唔方得到報"
        self.assertLoggedEqual("wide characters count double", 10, GetDisplayLength(text), input_value=text)
        self.assertLoggedEqual("accented Latin counts single", 7, GetDisplayLength("réalisé"))


class WrapKeyDominatesTests(LoggedTestCase):
    """Tests for deciding whether one column is taller at any width."""

    def test_longer_lines_dominate(self) -> None:
        self.assertLoggedTrue("longer lines dominate", WrapKeyDominates((5, 5), (4, 4)))
        self.assertLoggedFalse("shorter lines do not dominate", WrapKeyDominates((4, 4), (5, 5)))

    def test_equal_keys_dominate_each_other(self) -> None:
        self.assertLoggedTrue("equal keys dominate", WrapKeyDominates((3, 5), (3, 5)))

    def test_more_lines_dominate_one_long_line_of_similar_length(self) -> None:
        self.assertLoggedTrue("two long lines dominate one", WrapKeyDominates((5, 5), (4,)))

    def test_fewer_lines_never_dominate(self) -> None:
        self.assertLoggedFalse("one long line vs three short", WrapKeyDominates((9,), (1, 1, 1)))

    def test_neither_dominates_when_taller_column_depends_on_width(self) -> None:
        self.assertLoggedFalse("three short lines vs one long", WrapKeyDominates((1, 1, 1), (9,)))


class LineItemSizeKeyTests(LoggedTestCase):
    """Tests for the size key a subtitle line uses to share cached row sizes."""

    def _create_line(self, text : str, translation : str|None) -> LineItem:
        model : dict[str, str|int|float] = { 'start': "0:00:01,000", 'end': "0:00:02,000", 'text': text }
        if translation is not None:
            model['translation'] = translation
        return LineItem(1, model)

    def test_key_is_taller_column_when_it_dominates(self) -> None:
        line = self._create_line("x" * 50 + "\n" + "x" * 50, "x" * 30)
        self.assertLoggedEqual("key is the original alone", (GetWrapKey(line.line_text),), line.size_key)

    def test_same_key_whichever_column_is_taller(self) -> None:
        taller_original = self._create_line("x" * 50 + "\n" + "x" * 50, "x" * 30)
        taller_translation = self._create_line("x" * 30, "x" * 50 + "\n" + "x" * 50)
        self.assertLoggedEqual("rows share a key", taller_original.size_key, taller_translation.size_key)

    def test_key_includes_both_columns_when_neither_dominates(self) -> None:
        line = self._create_line("a\nb\nc", "x" * 90)
        self.assertLoggedEqual("key has both columns", 2, len(line.size_key))

    def test_same_key_when_columns_are_swapped(self) -> None:
        line = self._create_line("a\nb\nc", "x" * 90)
        swapped = self._create_line("x" * 90, "c\nb\na")
        self.assertLoggedEqual("column and line order do not matter", line.size_key, swapped.size_key)

    def test_untranslated_line_uses_original(self) -> None:
        line = self._create_line("x" * 25, None)
        self.assertLoggedEqual("key is the original alone", (GetWrapKey(line.line_text),), line.size_key)

    def test_wide_original_dominates_longer_latin_translation(self) -> None:
        line = self._create_line("唔方得到報唔方得到報唔方得到報", "x" * 20)
        self.assertLoggedEqual("key is the wider original", (GetWrapKey(line.line_text),), line.size_key)
