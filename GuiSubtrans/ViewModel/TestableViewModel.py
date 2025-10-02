from typing import Any, cast

from PySide6.QtCore import QModelIndex

from GuiSubtrans.ViewModel.BatchItem import BatchItem
from GuiSubtrans.ViewModel.LineItem import LineItem
from GuiSubtrans.ViewModel.SceneItem import SceneItem
from GuiSubtrans.ViewModel.ViewModel import ProjectViewModel
from PySubtrans.Helpers.TestCases import BuildSubtitlesFromLineCounts, SubtitleTestCase
from PySubtrans.Helpers.Tests import log_input_expected_result
from PySubtrans.Subtitles import Subtitles


class TestableViewModel(ProjectViewModel):
    """
    Subclass of ProjectViewModel that tracks signals for testing.
    """
    def __init__(self, test_case : SubtitleTestCase):
        super().__init__()
        self.test = test_case
        self.signal_history : list[dict] = []

        # Connect to all relevant signals
        self.dataChanged.connect(self._track_data_changed)
        self.layoutChanged.connect(self._track_layout_changed)
        self.modelReset.connect(self._track_model_reset)

    def CreateSubtitles(self, line_counts : list[list[int]]) -> Subtitles:
        """Helper to create and set up subtitles from line counts"""
        subtitles = BuildSubtitlesFromLineCounts(line_counts)
        self.CreateModel(subtitles)
        self.clear_signal_history()  # Clear any signals from initial setup
        return subtitles

    def test_get_scene_item(self, scene_number : int) -> SceneItem:
        """
        Helper to retrieve a scene item from the view model by scene number.
        Scene numbers are stable identifiers, not row positions.
        """
        scene_item = self.model.get(scene_number)

        log_input_expected_result(f"scene {scene_number} exists", True, scene_item is not None)
        self.test.assertIsNotNone(scene_item)

        log_input_expected_result(f"scene {scene_number} type", SceneItem, type(scene_item))
        self.test.assertEqual(type(scene_item), SceneItem)

        return cast(SceneItem, scene_item)

    def test_get_batch_item(self, scene_number : int, batch_number : int) -> BatchItem:
        """
        Helper to retrieve a batch item by scene and batch numbers.
        """
        scene_item = self.test_get_scene_item(scene_number)
        batch_item_qt = scene_item.child(batch_number - 1, 0)

        log_input_expected_result(f"batch ({scene_number},{batch_number}) exists", True, batch_item_qt is not None)
        self.test.assertIsNotNone(batch_item_qt)

        log_input_expected_result(f"batch ({scene_number},{batch_number}) type", BatchItem, type(batch_item_qt))
        self.test.assertEqual(type(batch_item_qt), BatchItem)

        return cast(BatchItem, batch_item_qt)

    def test_get_line_item(self, scene_number : int, batch_number : int, line_number : int) -> LineItem:
        """
        Helper to retrieve a line item by scene, batch, and line numbers.
        """
        batch_item = self.test_get_batch_item(scene_number, batch_number)
        line_item_qt = batch_item.child(line_number - 1, 0)

        log_input_expected_result(f"line ({scene_number},{batch_number},{line_number}) exists", True, line_item_qt is not None)
        self.test.assertIsNotNone(line_item_qt)

        log_input_expected_result(f"line ({scene_number},{batch_number},{line_number}) type", LineItem, type(line_item_qt))
        self.test.assertEqual(type(line_item_qt), LineItem)

        return cast(LineItem, line_item_qt)

    def get_line_numbers_in_batch(self, scene_number : int, batch_number : int) -> list[int]:
        """
        Helper to retrieve all global line numbers from a batch.
        Returns a list of line numbers.
        """
        batch_item = self.test_get_batch_item(scene_number, batch_number)
        line_numbers = []
        for i in range(batch_item.line_count):
            line_item = batch_item.child(i, 0)
            if isinstance(line_item, LineItem):
                line_numbers.append(line_item.number)
        return line_numbers

    def clear_signal_history(self) -> None:
        """Clear signal history between test operations"""
        self.signal_history.clear()

    def assert_signal_emitted(self, signal_name : str, expected_count : int|None = None) -> list[dict]:
        """
        Assert that a specific signal was emitted.
        Returns the list of matching signals for further inspection.

        Args:
            signal_name: Name of the signal ('dataChanged', 'layoutChanged', 'modelReset')
            expected_count: Expected number of times signal was emitted (None = at least once)
        """
        matching_signals = [s for s in self.signal_history if s['signal'] == signal_name]

        if expected_count is None:
            log_input_expected_result(f"{signal_name} emitted", True, len(matching_signals) > 0)
            self.test.assertGreater(len(matching_signals), 0, f"Expected {signal_name} to be emitted")
        else:
            log_input_expected_result(f"{signal_name} count", expected_count, len(matching_signals))
            self.test.assertEqual(len(matching_signals), expected_count,
                                f"Expected {signal_name} to be emitted {expected_count} times, got {len(matching_signals)}")

        return matching_signals

    def assert_no_signal_emitted(self, signal_name : str) -> None:
        """
        Assert that a specific signal was NOT emitted.

        Args:
            signal_name: Name of the signal ('dataChanged', 'layoutChanged', 'modelReset')
        """
        matching_signals = [s for s in self.signal_history if s['signal'] == signal_name]
        log_input_expected_result(f"{signal_name} not emitted", 0, len(matching_signals))
        self.test.assertEqual(len(matching_signals), 0,
                            f"Expected {signal_name} to NOT be emitted, but it was emitted {len(matching_signals)} times")

    def assert_scene_fields(self, test_data : list[tuple[int, str, Any]]) -> None:
        """
        Helper to assert multiple scene fields at once.
        test_data: list of (scene_num, field_name, expected_value)
        """
        for scene_num, field, expected in test_data:
            scene = self.test_get_scene_item(scene_num)
            actual = getattr(scene, field)
            log_input_expected_result(f"scene {scene_num} {field}", expected, actual)
            self.test.assertEqual(actual, expected)

    def assert_batch_fields(self, test_data : list[tuple[int, int, str, Any]]) -> None:
        """
        Helper to assert multiple batch fields at once.
        test_data: list of (scene_num, batch_num, field_name, expected_value)
        """
        for scene_num, batch_num, field, expected in test_data:
            batch = self.test_get_batch_item(scene_num, batch_num)
            actual = getattr(batch, field)
            log_input_expected_result(f"batch ({scene_num},{batch_num}) {field}", expected, actual)
            self.test.assertEqual(actual, expected)

    def assert_line_texts(self, test_data : list[tuple[int, int, int, int, str]]) -> None:
        """
        Helper to assert multiple line texts at once.
        test_data: list of (scene_num, batch_num, line_idx, line_num, expected_text)
        line_idx can be negative to index from the end
        """
        for scene_num, batch_num, line_idx, line_num, expected_text in test_data:
            batch = self.test_get_batch_item(scene_num, batch_num)
            # Handle negative indices manually since Qt doesn't support them
            actual_idx = line_idx if line_idx >= 0 else batch.line_count + line_idx
            line = cast(LineItem, batch.child(actual_idx, 0))
            log_input_expected_result(f"line ({line_num}) text", expected_text, line.line_text)
            self.test.assertEqual(line.line_text, expected_text)

    def _track_data_changed(self, topLeft : QModelIndex, bottomRight : QModelIndex, roles : list[int]) -> None:
        """Track dataChanged signals"""
        self.signal_history.append({
            'signal': 'dataChanged',
            'topLeft': topLeft,
            'bottomRight': bottomRight,
            'roles': roles
        })

    def _track_layout_changed(self) -> None:
        """Track layoutChanged signals"""
        self.signal_history.append({'signal': 'layoutChanged'})

    def _track_model_reset(self) -> None:
        """Track modelReset signals"""
        self.signal_history.append({'signal': 'modelReset'})


