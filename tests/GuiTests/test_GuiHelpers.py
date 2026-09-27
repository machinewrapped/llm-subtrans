from GuiSubtrans.GuiHelpers import GetWrapKey
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
