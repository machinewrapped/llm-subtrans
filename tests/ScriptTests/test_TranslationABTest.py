import contextlib
import io
from datetime import timedelta

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Helpers.Tests import log_input_expected_error, skip_if_debugger_attached
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleLine import SubtitleLine
from scripts.translation_ab_test import (ComparePair, CreateParser, FindSites, LengthBreakdown, MeasureArm, ParseArm,
                                         ParseOverride, ParseVerdicts, SignTestPValue)


def _line(number : int, text : str) -> SubtitleLine:
    return SubtitleLine.Construct(number, timedelta(seconds=number * 2), timedelta(seconds=number * 2 + 1.5), text)


class TestTranslationABTest(LoggedTestCase):
    """Tests for the pure helpers of the translation A/B test script."""

    def test_overrides_read_booleans_and_numbers(self) -> None:
        """KEY=VALUE overrides become booleans and numbers where they look like them, and strings otherwise."""
        cases = {
            "preprocess_subtitles=true": ('preprocess_subtitles', True),
            "max_batch_size=30": ('max_batch_size', 30),
            "temperature=0.7": ('temperature', 0.7),
            "instruction_file=a=b.txt": ('instruction_file', "a=b.txt"),
            "min_gap=-2": ('min_gap', -2),
            "rate=1e3": ('rate', 1000.0),
            "model=v1.2": ('model', "v1.2"),
        }

        for override, expected in cases.items():
            self.assertLoggedEqual("parsed override", expected, ParseOverride(override), input_value=override)

    def test_arm_settings_are_layered(self) -> None:
        """Command-line overrides win over the arm's settings, and a PROVIDER:MODEL spec wins over both."""
        base = SettingsType({'provider': "Gemini", 'model': "flash", 'temperature': 0.2, 'instruction_file': "a.txt"})

        arm = ParseArm('B', None, base, ["temperature=0.5"])
        self.assertLoggedEqual("provider from settings", "Gemini", arm.provider)
        self.assertLoggedEqual("override wins", 0.5, arm.settings.get_float('temperature'))
        self.assertLoggedEqual("setting kept", "a.txt", arm.settings.get_str('instruction_file'))

        arm = ParseArm('B', "OpenRouter:other", base, [])
        self.assertLoggedEqual("spec provider wins", "OpenRouter", arm.provider)
        self.assertLoggedEqual("spec model wins", "other", arm.settings.get_str('model'))

    def test_description_leaves_out_credentials(self) -> None:
        """Keys, tokens and passwords are not shown in an arm's description, which goes into shared reports."""
        settings = SettingsType({'provider': "Gemini", 'model': "flash", 'api_key': "sk-secret", 'access_token': "t0k3n", 'temperature': 0.5})
        arm = ParseArm('A', None, settings, ["password=hunter2"])

        self.assertLoggedEqual("description", "Gemini:flash (temperature=0.5)", arm.description)

    @skip_if_debugger_attached
    def test_invalid_counts_are_rejected(self) -> None:
        """Counts that could not be carried out are rejected as arguments, before anything is translated."""
        parser = CreateParser()
        for arguments in (["--judge-batch", "0"], ["--max-sites", "-1"], ["--runs", "0"], ["--min-change", "-0.1"]):
            with self.assertRaises(SystemExit) as context, contextlib.redirect_stderr(io.StringIO()):
                parser.parse_args(["input.srt", "-l", "English", "-o", "out"] + arguments)
            self.assertLoggedEqual("argument error exit code", 2, context.exception.code, input_value=arguments)

    @skip_if_debugger_attached
    def test_arm_needs_a_provider_and_model(self) -> None:
        """An arm with no provider and model anywhere is an error."""
        try:
            ParseArm('A', None, SettingsType({'temperature': 0.2}), [])
            self.fail("Expected ValueError")
        except ValueError as e:
            log_input_expected_error("no provider or model", ValueError, e)

    def test_sites_are_lines_translated_differently(self) -> None:
        """Only lines both arms translated, and translated differently, are judged."""
        originals = [_line(1, "하나."), _line(2, "둘."), _line(3, "셋."), _line(4, "넷.")]
        first = {1: "One.", 2: "Two.", 3: "Three."}
        second = {1: "One.", 2: "Two!", 3: "Three.\n", 4: "Four."}
        sites = FindSites(originals, first, second, min_change=0.0)

        self.assertLoggedEqual("site numbers", [2], [site.number for site in sites])
        self.assertLoggedEqual("source before", ["하나."], sites[0].source_before)
        self.assertLoggedEqual("source after", ["셋.", "넷."], sites[0].source_after)
        self.assertLoggedEqual("translation before", ["One."], sites[0].translations_before['A'])
        self.assertLoggedEqual("untranslated context left blank", ["Three.\n", "Four."], sites[0].translations_after['B'])
        self.assertLoggedEqual("missing context line", ["Three.", ""], sites[0].translations_after['A'])

    def test_min_change_keeps_only_length_changes(self) -> None:
        """With min_change, rewording of the same length is not judged."""
        originals = [_line(1, "하나."), _line(2, "둘.")]
        first = {1: "This is the first line.", 2: "This is a much longer second line of dialogue."}
        second = {1: "This is the 1st line.", 2: "A shorter second line."}
        sites = FindSites(originals, first, second, min_change=0.2)

        self.assertLoggedEqual("site numbers", [2], [site.number for site in sites])

    def test_verdicts_are_unblinded(self) -> None:
        """X and Y are mapped back to each site's arms, and lines that are not verdicts are ignored."""
        key = {1: {'X': 'A', 'Y': 'B'}, 2: {'X': 'B', 'Y': 'A'}, 3: {'X': 'A', 'Y': 'B'}}
        reply = "Here you go:\n1|X|high|Clearer.\n2 | x | Medium | Keeps the name.\n3|same|low|Equivalent.\n9|Y|high|Not a site."
        verdicts = ParseVerdicts(reply, key)

        self.assertLoggedEqual("unblinded winners", {1: 'A', 2: 'B', 3: 'same'}, {number: verdict[0] for number, verdict in verdicts.items()})
        self.assertLoggedEqual("confidence normalised", 'medium', verdicts[2][1])

    def test_length_breakdown_groups_by_the_longer_arm(self) -> None:
        """Verdicts are grouped by which arm's translation is noticeably longer."""
        originals = [_line(1, "하나."), _line(2, "둘."), _line(3, "셋.")]
        first = {1: "A long and detailed translation.", 2: "Short.", 3: "Similar one."}
        second = {1: "Brief.", 2: "A long and detailed translation.", 3: "Similar two."}
        sites = FindSites(originals, first, second, min_change=0.0)
        verdicts = {1: ('A', 'high', ''), 2: ('A', 'low', ''), 3: ('B', 'medium', '')}

        self.assertLoggedEqual("groups", [('A longer', 1, 1, 0), ('B longer', 1, 1, 0), ('Similar length', 1, 0, 1)],
                               LengthBreakdown(sites, verdicts))

    def test_arm_statistics(self) -> None:
        """Line lengths, long lines, rows, dialogue and length against the other arm are counted."""
        texts = {1: "Short.", 2: "A much longer line of subtitle text.", 3: "- Who?\n- Me.", 4: "First row\nsecond row"}
        other = {1: "Short!", 2: "Brief.", 3: "- Who is it?\n- Me.", 5: "Unmatched."}
        stats = MeasureArm(texts, other, long_line=20)

        self.assertLoggedEqual("lines", 4, stats.lines)
        self.assertLoggedEqual("long lines", 1, stats.long_lines)
        self.assertLoggedEqual("multi-row lines", 2, stats.multi_row)
        self.assertLoggedEqual("dialogue lines", 1, stats.dialogue)
        self.assertLoggedEqual("longer than the other arm", 1, stats.longer)
        self.assertLoggedEqual("shorter than the other arm", 1, stats.shorter)

    def test_pair_statistics(self) -> None:
        """Lines are identical, identical but for layout, or worded differently."""
        first = {1: "Same.", 2: "Two rows\nof text.", 3: "One way.", 4: "Only here."}
        second = {1: "Same.", 2: "Two rows of text.", 3: "Another way."}
        pair = ComparePair(first, second)

        self.assertLoggedEqual("counts", (3, 1, 1, 1), (pair.both, pair.identical, pair.layout_only, pair.different))

    def test_sign_test(self) -> None:
        """An even split is no evidence of a difference, and a one-sided one is strong evidence."""
        self.assertLoggedEqual("even split", 1.0, SignTestPValue(5, 5))
        self.assertLoggedEqual("ten to none", 2 / 1024, SignTestPValue(10, 0))
        self.assertLoggedEqual("no verdicts", 1.0, SignTestPValue(0, 0))
