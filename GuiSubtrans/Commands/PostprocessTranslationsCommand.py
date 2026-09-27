from __future__ import annotations

import logging

from GuiSubtrans.Command import Command, CommandError
from GuiSubtrans.ProjectDataModel import ProjectDataModel
from GuiSubtrans.ViewModel.ViewModelUpdate import ModelUpdate
from GuiSubtrans.ViewModel.ViewModelUpdateSection import BatchKey
from PySubtrans.Helpers import FormatNumberRanges
from PySubtrans.Helpers.Localization import _
from PySubtrans.SubtitleBatch import SubtitleBatch
from PySubtrans.SubtitleEditor import SubtitleEditor
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.SubtitleLine import SubtitleLine
from PySubtrans.SubtitleProcessor import SubtitleProcessor
from PySubtrans.SubtitleValidator import SubtitleValidator
from PySubtrans.Subtitles import Subtitles


class PostprocessTranslationsCommand(Command):
    """Post-process selected translated lines in one or more subtitle batches."""

    def __init__(self, line_numbers : list[int], datamodel : ProjectDataModel|None = None):
        super().__init__(datamodel)
        self.line_numbers : list[int] = sorted(set(line_numbers))
        self.undo_data : dict[int, str|None] = {}

    def execute(self) -> bool:
        """Run the configured subtitle post-processor on the selected lines."""
        if not self.line_numbers:
            raise CommandError(_("No lines selected to post-process"), command=self)

        if not self.datamodel or not self.datamodel.project:
            raise CommandError(_("No project data"), command=self)

        subtitles : Subtitles = self.datamodel.project.subtitles
        processor = SubtitleProcessor(self.datamodel.project_options)

        logging.info(_("Post-processing lines {lines}").format(
            lines=FormatNumberRanges(self.line_numbers)))

        self.ClearModelUpdates()
        self.undo_data = {}

        selected_lines = set(self.line_numbers)

        with SubtitleEditor(subtitles) as editor:
            try:
                batches = subtitles.GetBatchesContainingLines(self.line_numbers)
            except (SubtitleError, ValueError) as error:
                raise CommandError(_(
                    "Unable to find selected lines: {error}"
                ).format(error=error), command=self)

            found_lines = {line.number for batch in batches for line in batch.originals}
            if not selected_lines.issubset(found_lines):
                raise CommandError(_("Some selected lines were not found"), command=self)

            # Post-process every batch before mutating any of them, so a
            # failure part-way through does not leave some batches changed with no undo data.
            # Untranslated lines are skipped, e.g. lines emptied by filler word removal.
            processed_batches : list[tuple[SubtitleBatch, list[SubtitleLine]]] = []
            for batch in batches:
                lines_to_process = [
                    line for line in batch.translated
                    if line.number in selected_lines and line.text is not None
                ]

                if lines_to_process:
                    processed_batches.append((batch, processor.PostprocessSubtitles(lines_to_process)))

            if not processed_batches:
                raise CommandError(_("No translated lines selected to post-process"), command=self)

            for batch, processed_lines in processed_batches:
                model_update : ModelUpdate = self.AddModelUpdate()
                for processed_line in processed_lines:
                    previous_line = batch.GetTranslatedLine(processed_line.number)
                    self.undo_data[processed_line.number] = previous_line.text if previous_line else None

                    self._set_translation(editor, model_update, batch, processed_line.number, processed_line.text)

                self._revalidate_batch(model_update, batch)

        return True

    def undo(self) -> bool:
        """Restore the translations captured before post-processing."""
        if not self.datamodel or not self.datamodel.project:
            raise CommandError(_("No project data"), command=self)

        if not self.undo_data:
            raise CommandError(_("No undo data available"), command=self)

        subtitles : Subtitles = self.datamodel.project.subtitles

        self.ClearModelUpdates()

        lines_by_batch : dict[BatchKey, tuple[SubtitleBatch, dict[int, str|None]]] = {}
        for line_number, previous_text in self.undo_data.items():
            batch : SubtitleBatch|None = subtitles.GetBatchContainingLine(line_number)
            if not batch:
                raise CommandError(_("Line {line} not found in any batch").format(line=line_number), command=self)

            batch_key : BatchKey = (batch.scene, batch.number)
            _existing_batch, line_updates = lines_by_batch.setdefault(batch_key, (batch, {}))
            line_updates[line_number] = previous_text

        with SubtitleEditor(subtitles) as editor:
            for batch, line_updates in lines_by_batch.values():
                model_update : ModelUpdate = self.AddModelUpdate()
                for line_number, previous_text in line_updates.items():
                    self._set_translation(editor, model_update, batch, line_number, previous_text)

                self._revalidate_batch(model_update, batch)

        return True

    def _set_translation(
        self, editor : SubtitleEditor, model_update : ModelUpdate, batch : SubtitleBatch, line_number : int, text : str|None
    ) -> None:
        """Update a line's translation and queue the corresponding view-model change."""
        editor.UpdateLine(line_number, {'translation': text})

        if text is None:
            # UpdateLine only rebuilds batch.translated from a non-None cache, so an emptied
            # translation leaves a stale entry behind - remove it explicitly.
            batch.translated = [line for line in batch.translated if line.number != line_number]

        model_update.lines.update((batch.scene, batch.number, line_number), {'translation': text})

    def _revalidate_batch(self, model_update : ModelUpdate, batch : SubtitleBatch) -> None:
        """Recompute the batch's validation errors after its translations changed."""
        if not self.datamodel:
            return

        validator = SubtitleValidator(self.datamodel.project_options)
        validator.ValidateBatch(batch)
        model_update.batches.update((batch.scene, batch.number), {'errors': batch.errors})
