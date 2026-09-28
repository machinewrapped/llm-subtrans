from unittest.mock import Mock

from GuiSubtrans.Command import CommandError
from GuiSubtrans.Commands.PostprocessTranslationsCommand import PostprocessTranslationsCommand
from GuiSubtrans.GuiSubtitleTestCase import GuiSubtitleTestCase
from GuiSubtrans.ProjectSelection import ProjectSelection, SelectionBatch, SelectionLine
from GuiSubtrans.Widgets.SelectionView import SelectionView
from PySubtrans.Helpers.TestCases import BuildSubtitlesFromLineCounts
from PySubtrans.Helpers.Tests import log_input_expected_error, skip_if_debugger_attached
from PySubtrans.SubtitleEditor import SubtitleEditor
from PySubtrans.SubtitleLine import SubtitleLine


class PostprocessTranslationsCommandTests(GuiSubtitleTestCase):
    """Test post-processing selected batches and its selection-view action."""

    def test_postprocesses_selected_lines_and_undo_restores_original_lines(self) -> None:
        self.options.update({
            'remove_filler_words': True,
            'break_long_lines': False,
            'break_dialog_on_one_line': False,
            'normalise_dialog_tags': False,
            'convert_wide_dashes': False,
            'full_width_punctuation': False,
        })

        subtitles = BuildSubtitlesFromLineCounts([[1, 1]])
        datamodel = self.create_project_datamodel(subtitles)

        for batch in subtitles.scenes[0].batches:
            batch.translated = [SubtitleLine.Construct(
                line.number,
                line.start,
                line.end,
                'um, translated line',
            ) for line in batch.originals]

        command = PostprocessTranslationsCommand([1, 2], datamodel)
        self.assertLoggedTrue('postprocess command executes', command.execute())

        processed_texts = [
            line.text
            for batch in subtitles.scenes[0].batches
            for line in batch.translated
        ]
        self.assertLoggedSequenceEqual(
            'all selected lines are postprocessed',
            ['translated line', 'translated line'],
            processed_texts,
        )
        self.assertLoggedEqual('one model update per batch', 2, len(command.model_updates))

        self.assertLoggedTrue('postprocess command undoes', command.undo())
        restored_texts = [
            line.text
            for batch in subtitles.scenes[0].batches
            for line in batch.translated
        ]
        self.assertLoggedSequenceEqual(
            'undo restores all translated lines',
            ['um, translated line', 'um, translated line'],
            restored_texts,
        )

    def test_postprocess_syncs_original_line_translation_cache(self) -> None:
        self.options.update({
            'remove_filler_words': True,
            'break_long_lines': False,
            'break_dialog_on_one_line': False,
            'normalise_dialog_tags': False,
            'convert_wide_dashes': False,
            'full_width_punctuation': False,
        })

        subtitles = BuildSubtitlesFromLineCounts([[1]])
        datamodel = self.create_project_datamodel(subtitles)
        batch = subtitles.scenes[0].batches[0]
        batch.translated = [SubtitleLine.Construct(
            line.number,
            line.start,
            line.end,
            'um, translated line',
        ) for line in batch.originals]
        for line in batch.originals:
            line.translation = 'um, translated line'

        command = PostprocessTranslationsCommand([1], datamodel)
        self.assertLoggedTrue('postprocess command executes', command.execute())

        original_line = batch.GetOriginalLine(1)
        self.assertLoggedIsNotNone('original line exists', original_line)
        assert original_line is not None
        self.assertLoggedEqual(
            'original line translation cache is synced with the postprocessed text',
            'translated line',
            original_line.translation,
        )

        with SubtitleEditor(subtitles) as editor:
            editor.UpdateLine(1, {'text': 'edited original text'})

        translated_line = batch.GetTranslatedLine(1)
        self.assertLoggedIsNotNone('translated line exists', translated_line)
        assert translated_line is not None
        self.assertLoggedEqual(
            'editing the original line does not revert the postprocessed translation',
            'translated line',
            translated_line.text,
        )

        self.assertLoggedTrue('postprocess command undoes', command.undo())

        original_line = batch.GetOriginalLine(1)
        self.assertLoggedIsNotNone('original line exists after undo', original_line)
        assert original_line is not None
        self.assertLoggedEqual(
            'undo restores the original line translation cache',
            'um, translated line',
            original_line.translation,
        )

    def test_postprocess_skips_untranslated_lines(self) -> None:
        self.options.update({
            'remove_filler_words': True,
            'break_long_lines': False,
            'break_dialog_on_one_line': False,
            'normalise_dialog_tags': False,
            'convert_wide_dashes': False,
            'full_width_punctuation': False,
        })

        subtitles = BuildSubtitlesFromLineCounts([[2], [1]])
        datamodel = self.create_project_datamodel(subtitles)

        # Line 2 has no translation, e.g. because it was emptied by filler word removal
        partial_batch = subtitles.scenes[0].batches[0]
        partial_batch.translated = [SubtitleLine.Construct(
            line.number, line.start, line.end, 'um, translated line',
        ) for line in partial_batch.originals if line.number == 1]

        untranslated_batch = subtitles.scenes[1].batches[0]
        untranslated_batch.translated = []

        command = PostprocessTranslationsCommand([1, 2, 3], datamodel)
        self.assertLoggedTrue('postprocess command executes', command.execute())

        self.assertLoggedSequenceEqual(
            'the translated line is postprocessed',
            ['translated line'],
            [line.text for line in partial_batch.translated],
        )
        self.assertLoggedSequenceEqual(
            'only translated lines have undo data',
            [1],
            list(command.undo_data.keys()),
        )
        self.assertLoggedEqual('only the batch with translated lines is updated', 1, len(command.model_updates))
        self.assertLoggedEqual('the untranslated batch is untouched', 0, len(untranslated_batch.translated))

    @skip_if_debugger_attached
    def test_postprocess_fails_if_no_selected_lines_are_translated(self) -> None:
        subtitles = BuildSubtitlesFromLineCounts([[2]])
        datamodel = self.create_project_datamodel(subtitles)
        subtitles.scenes[0].batches[0].translated = []

        command = PostprocessTranslationsCommand([1, 2], datamodel)
        with self.assertRaises(CommandError) as context:
            command.execute()

        log_input_expected_error([1, 2], CommandError, context.exception)
        self.assertLoggedEqual('no undo data was recorded', 0, len(command.undo_data))
        self.assertLoggedEqual('no model updates were queued', 0, len(command.model_updates))

    def test_postprocess_removes_stale_translated_line_when_result_is_empty(self) -> None:
        self.options.update({
            'remove_filler_words': True,
            'break_long_lines': False,
            'break_dialog_on_one_line': False,
            'normalise_dialog_tags': False,
            'convert_wide_dashes': False,
            'full_width_punctuation': False,
        })

        subtitles = BuildSubtitlesFromLineCounts([[1]])
        datamodel = self.create_project_datamodel(subtitles)
        batch = subtitles.scenes[0].batches[0]
        batch.translated = [SubtitleLine.Construct(
            line.number, line.start, line.end, 'Um,',
        ) for line in batch.originals]
        for line in batch.originals:
            line.translation = 'Um,'

        command = PostprocessTranslationsCommand([1], datamodel)
        self.assertLoggedTrue('postprocess command executes', command.execute())

        self.assertLoggedIsNone(
            'the stale translated line is removed rather than left with the old text',
            batch.GetTranslatedLine(1),
        )
        original_line = batch.GetOriginalLine(1)
        self.assertLoggedIsNotNone('original line exists', original_line)
        assert original_line is not None
        self.assertLoggedIsNone(
            'the original line translation cache is cleared',
            original_line.translation,
        )

        self.assertLoggedTrue('postprocess command undoes', command.undo())

        translated_line = batch.GetTranslatedLine(1)
        self.assertLoggedIsNotNone('undo restores the translated line', translated_line)
        assert translated_line is not None
        self.assertLoggedEqual(
            'undo restores the original translated text',
            'Um,',
            translated_line.text,
        )

    def test_postprocess_revalidates_batch_and_updates_model_errors(self) -> None:
        self.options.update({
            'remove_filler_words': True,
            'break_long_lines': False,
            'break_dialog_on_one_line': False,
            'normalise_dialog_tags': False,
            'convert_wide_dashes': False,
            'full_width_punctuation': False,
        })

        subtitles = BuildSubtitlesFromLineCounts([[1]])
        datamodel = self.create_project_datamodel(subtitles)
        batch = subtitles.scenes[0].batches[0]
        batch.translated = [SubtitleLine.Construct(
            line.number, line.start, line.end, 'Um,',
        ) for line in batch.originals]

        command = PostprocessTranslationsCommand([1], datamodel)
        self.assertLoggedTrue('postprocess command executes', command.execute())

        self.assertLoggedEqual('one model update is queued', 1, len(command.model_updates))
        batch_updates = command.model_updates[0].batches.updates
        self.assertLoggedIn(
            'the model update includes the batch errors',
            (batch.scene, batch.number),
            batch_updates,
        )
        self.assertLoggedIn(
            'the batch is revalidated as untranslated after the translation is emptied',
            'errors',
            batch_updates[(batch.scene, batch.number)],
        )

    def test_postprocess_button_requires_any_selected_line_translated(self) -> None:
        action_handler = Mock()
        view = SelectionView(action_handler)

        view.ShowSelection(ProjectSelection())
        self.assertLoggedTrue(
            'postprocess button is hidden without selected lines',
            view._postprocess_button.isHidden(),
        )

        selection = ProjectSelection()
        selection.batches[(1, 1)] = SelectionBatch((1, 1), selected=True, translated=False)
        selection.lines[1] = SelectionLine(1, 1, 1, False, translated=False)
        view.ShowSelection(selection)
        self.assertLoggedTrue(
            'postprocess button is hidden when no selected lines are translated',
            view._postprocess_button.isHidden(),
        )

        selection.batches[(1, 2)] = SelectionBatch((1, 2), selected=True, translated=True)
        selection.lines[2] = SelectionLine(1, 2, 2, False, translated=True)
        view.ShowSelection(selection)
        self.assertLoggedFalse(
            'postprocess button is shown when some selected lines are translated',
            view._postprocess_button.isHidden(),
        )

        view.deleteLater()

    def test_postprocesses_only_selected_lines_in_a_batch(self) -> None:
        self.options.update({
            'remove_filler_words': True,
            'break_long_lines': False,
            'break_dialog_on_one_line': False,
            'normalise_dialog_tags': False,
            'convert_wide_dashes': False,
            'full_width_punctuation': False,
        })

        subtitles = BuildSubtitlesFromLineCounts([[2]])
        datamodel = self.create_project_datamodel(subtitles)
        batch = subtitles.scenes[0].batches[0]
        batch.translated = [SubtitleLine.Construct(
            line.number,
            line.start,
            line.end,
            'um, translated line' if line.number == 2 else 'untouched line',
        ) for line in batch.originals]

        command = PostprocessTranslationsCommand([2], datamodel)
        self.assertLoggedTrue('partial postprocess command executes', command.execute())
        self.assertLoggedSequenceEqual(
            'only selected line is postprocessed',
            ['untouched line', 'translated line'],
            [line.text for line in batch.translated],
        )

        self.assertLoggedTrue('partial postprocess command undoes', command.undo())
        self.assertLoggedSequenceEqual(
            'undo restores unselected and selected lines',
            ['untouched line', 'um, translated line'],
            [line.text for line in batch.translated],
        )
