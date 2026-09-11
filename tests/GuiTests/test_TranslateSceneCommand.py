"""Tests for GUI translation command completion reporting."""
import logging
from datetime import timedelta
from unittest.mock import Mock, patch

from GuiSubtrans.Commands.TranslateSceneCommand import TranslateSceneCommand
from GuiSubtrans.ProjectDataModel import ProjectDataModel
from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Options import Options
from PySubtrans.SubtitleBatch import SubtitleBatch
from PySubtrans.SubtitleLine import SubtitleLine
from PySubtrans.SubtitleScene import SubtitleScene
from PySubtrans.Subtitles import Subtitles
from PySubtrans.Translation import Translation
from PySubtrans.TranslationEvents import TranslationEvents


class FakeTranslationCommandTranslator:
    """Populate selected batches with deterministic provider responses."""

    def __init__(self, *_args, **_kwargs) -> None:
        self.events = TranslationEvents()
        self.errors: list = []
        self.stop_on_error = True
        self.aborted = False

    def TranslateScene(self, subtitles: Subtitles, scene: SubtitleScene, batch_numbers=None, line_numbers=None) -> None:
        _subtitles, _line_numbers = subtitles, line_numbers
        selected_batches = set(batch_numbers) if batch_numbers else None
        for batch in scene.batches:
            if selected_batches is None or batch.number in selected_batches:
                batch.translation = Translation({'text': 'translated text', 'cost': 0.0123})

    def StopTranslating(self) -> None:
        self.aborted = True


class TestTranslateSceneCommand(LoggedTestCase):
    """Verify that GUI translation commands report provider costs."""

    def test_completed_command_logs_selected_batch_cost(self) -> None:
        line = SubtitleLine.Construct(1, timedelta(), timedelta(seconds=1), 'source text')
        first_batch = SubtitleBatch({'scene': 1, 'batch': 1, 'originals': [line]})
        second_batch = SubtitleBatch({'scene': 1, 'batch': 2, 'originals': [line.Construct(2, line.start, line.end, 'other source')]})
        scene = SubtitleScene({'scene': 1, 'number': 1, 'batches': [first_batch, second_batch]})
        subtitles = Subtitles()
        subtitles.scenes = [scene]

        project = Mock(subtitles=subtitles)
        datamodel = Mock(spec=ProjectDataModel)
        datamodel.project = project
        datamodel.project_options = Options()
        datamodel.translation_provider = Mock()
        datamodel.translation_provider.ValidateSettings.return_value = True

        command = TranslateSceneCommand(1, batch_numbers=[1], datamodel=datamodel)
        with patch('GuiSubtrans.Commands.TranslateSceneCommand.SubtitleTranslator', FakeTranslationCommandTranslator), \
                self.assertLogs(level=logging.INFO) as captured:
            result = command.execute()

        self.assertLoggedTrue('translation command succeeds', result)
        self.assertLoggedEqual('selected batch cost', 0.0123, command.translation_cost)
        self.assertLoggedTrue(
            'GUI translation cost log',
            any('Translation cost for scene 1: $0.0123' in message for message in captured.output),
        )


if __name__ == '__main__':
    import unittest
    unittest.main()
