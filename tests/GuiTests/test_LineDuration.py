"""Lines outside the duration limits are marked for the subtitle view."""
import unittest
from datetime import timedelta

from GuiSubtrans.GuiSubtitleTestCase import GuiSubtitleTestCase
from GuiSubtrans.ViewModel.LineItem import LineDuration, LineDurationLimits, LineItem
from GuiSubtrans.ViewModel.ViewModel import ProjectViewModel
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleBatch import SubtitleBatch
from PySubtrans.SubtitleLine import SubtitleLine


class TestLineDuration(GuiSubtitleTestCase):
    def test_classify(self):
        """Lines shorter or longer than the limits are marked, and a zero limit is no limit."""
        limits = LineDurationLimits.FromOptions(SettingsType({'min_line_duration': 0.8, 'max_line_duration': 4.0}))
        unlimited = LineDurationLimits.FromOptions(SettingsType({'min_line_duration': 0.0, 'max_line_duration': 0.0}))

        cases = [
            ("short line", limits, 0.5, LineDuration.TOO_SHORT),
            ("ordinary line", limits, 2.0, LineDuration.WITHIN_LIMITS),
            ("line at the maximum", limits, 4.0, LineDuration.WITHIN_LIMITS),
            ("long line", limits, 12.6, LineDuration.TOO_LONG),
            ("no limits", unlimited, 12.6, LineDuration.WITHIN_LIMITS),
        ]
        for description, case_limits, seconds, expected in cases:
            self.assertLoggedEqual(description, expected, case_limits.Classify(timedelta(seconds=seconds)), input_value=seconds)

    def test_view_model_marks_lines(self):
        """The view model marks each line with how its duration compares with the project's limits."""
        batch = SubtitleBatch({'scene': 1, 'number': 1, 'originals': [
            SubtitleLine.Construct(1, timedelta(seconds=1), timedelta(seconds=3), "ordinary"),
            SubtitleLine.Construct(2, timedelta(seconds=4), timedelta(seconds=16), "long"),
            SubtitleLine.Construct(3, timedelta(seconds=17), timedelta(seconds=17.3), "short"),
        ]})
        viewmodel = ProjectViewModel(LineDurationLimits(min_seconds=0.8, max_seconds=4.0))

        batch_item = viewmodel.CreateBatchItem(1, batch)
        checks = [batch_item.lines[number].duration_check for number in (1, 2, 3)]

        self.assertLoggedEqual("line checks", [LineDuration.WITHIN_LIMITS, LineDuration.TOO_LONG, LineDuration.TOO_SHORT], checks)

    def test_settings_change_rechecks_lines(self):
        """Changing the duration limits re-checks the lines already in the view."""
        datamodel, _subtitles = self.create_datamodel_from_line_counts([[3]])
        datamodel.UpdateSettings(SettingsType({'min_line_duration': 0.0, 'max_line_duration': 0.0}))
        viewmodel = datamodel.CreateViewModel()
        lines = [line for scene in viewmodel.model.values() for batch in scene.batches.values() for line in batch.lines.values()]

        datamodel.UpdateSettings(SettingsType({'max_line_duration': 0.001}))
        viewmodel.ProcessUpdates()

        self.assertLoggedEqual("every line too long", [LineDuration.TOO_LONG] * len(lines), [line.duration_check for line in lines])

    def test_unmarked_line(self):
        """A line model without a check is within the limits."""
        item = LineItem(1, {'start': "00:00:01,000", 'end': "00:00:02,000", 'duration': "01,000", 'text': "hello"})

        self.assertLoggedEqual("default check", LineDuration.WITHIN_LIMITS, item.duration_check)


if __name__ == '__main__':
    unittest.main()
