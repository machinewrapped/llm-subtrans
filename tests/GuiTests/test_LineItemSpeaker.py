"""Speaker display in subtitle rows (viewmodel property + header format)."""
import unittest

from GuiSubtrans.GuiSubtitleTestCase import GuiSubtitleTestCase
from GuiSubtrans.ViewModel.LineItem import LineItem
from GuiSubtrans.Widgets.Widgets import FormatLineHeader, FormatLineMeta


def _model(speaker : str|None = None, style : str|None = None) -> dict:
    model = {
        'start': "00:10:58,342",
        'end': "00:10:58,742",
        'duration': "00,400",
        'gap': "24,600",
        'text': "hello",
    }
    if speaker is not None:
        model['speaker'] = speaker
    if style is not None:
        model['style'] = style
    return model


class TestLineItemSpeaker(GuiSubtitleTestCase):
    def test_speaker_property(self):
        """Viewmodel lines expose their speaker label."""
        item = LineItem(49, _model("Amina"))

        self.assertLoggedEqual("speaker", "Amina", item.speaker)

    def test_speaker_absent(self):
        """Lines without speakers report None, like style."""
        item = LineItem(49, _model())

        self.assertLoggedEqual("no speaker", None, item.speaker)

    def test_header_ignores_speaker(self):
        """Timecode headers stay clean with or without a speaker."""
        with_speaker = FormatLineHeader(LineItem(49, _model("Amina")))
        without_speaker = FormatLineHeader(LineItem(49, _model()))

        self.assertLoggedEqual("header", "[49] 00:10:58,342 --> 00:10:58,742", with_speaker)
        self.assertLoggedEqual("header unchanged", "[49] 00:10:58,342 --> 00:10:58,742", without_speaker)

    def test_meta_shows_speaker(self):
        """Speaker appears labelled alongside gap and length."""
        meta = FormatLineMeta(LineItem(49, _model("Amina")))

        self.assertLoggedEqual("meta", "Gap: 24,600, Length: 00,400, Speaker: Amina", meta)

    def test_meta_without_speaker_unchanged(self):
        """Rows without speakers render exactly as before."""
        meta = FormatLineMeta(LineItem(49, _model()))

        self.assertLoggedEqual("meta", "Gap: 24,600, Length: 00,400", meta)

    def test_meta_no_gap_with_speaker(self):
        """First lines show length plus speaker, no gap."""
        model = _model("Amina")
        del model['gap']
        meta = FormatLineMeta(LineItem(49, model))

        self.assertLoggedEqual("meta", "Length: 00,400, Speaker: Amina", meta)

    def test_meta_style_and_speaker(self):
        """Style and speaker annotations combine in order."""
        meta = FormatLineMeta(LineItem(49, _model("Amina", style="Default")))

        self.assertLoggedEqual("meta", "Gap: 24,600, Length: 00,400, Style: Default, Speaker: Amina", meta)


if __name__ == '__main__':
    unittest.main()
