from GuiSubtrans.Command import Command, CommandError, UndoError
from GuiSubtrans.ProjectDataModel import ProjectDataModel
from GuiSubtrans.ViewModel.ViewModelUpdate import ModelUpdate
from PySubtrans.SubtitleBatch import SubtitleBatch
from PySubtrans.Subtitles import Subtitles
from PySubtrans.SubtitleProject import SubtitleProject
from PySubtrans.Helpers.Localization import _

import logging

class MergeLinesCommand(Command):
    """
    Merge one or several lines together
    """
    def __init__(self, line_numbers : list[int], datamodel: ProjectDataModel|None = None):
        super().__init__(datamodel)
        self.line_numbers = sorted(line_numbers)
        self.undo_data = []

    def execute(self) -> bool:
        if not self.datamodel or not self.datamodel.project:
            raise CommandError(_("No project data"), command=self)

        subtitles : Subtitles = self.datamodel.project.subtitles

        if not subtitles:
            raise CommandError(_("No subtitles"), command=self)

        batches = subtitles.GetBatchesContainingLines(self.line_numbers)

        if not batches:
            raise CommandError(_("No batches found for lines to merge"), command=self)

        model_update : ModelUpdate =  self.AddModelUpdate()
        for batch in batches:
            batch_lines = [number for number in self.line_numbers 
                if batch.first_line_number is not None and batch.last_line_number is not None 
                and batch.first_line_number <= number <= batch.last_line_number
                ]

            originals = [batch.GetOriginalLine(line_number) for line_number in batch_lines]
            translated = [batch.GetTranslatedLine(line_number) for line_number in batch_lines]

            logging.info(_("Merging lines {lines} in batch {batch}").format(lines=str([number for number in batch_lines]), batch=str((batch.scene, batch.number))))

            if any([line is None for line in originals]):
                raise CommandError(_("Cannot merge lines, some lines are missing"), command=self)

            translated = [line for line in translated if line is not None]

            self.undo_data.append((batch.scene, batch.number, originals, translated))

            merged_line, merged_translated = subtitles.MergeLinesInBatch(batch.scene, batch.number, batch_lines)

            if not merged_line:
                raise CommandError(_("Failed to merge lines"), command=self)

            line_update = {
                'start': merged_line.start,
                'end': merged_line.end,
                'text': merged_line.text,
                }

            if merged_translated:
                line_update['translation'] = merged_translated.text

            model_update.lines.update((batch.scene, batch.number, merged_line.number), line_update)

            for line in batch_lines[1:]:
                model_update.lines.remove((batch.scene, batch.number, line))

        return True

    def undo(self):
        if not self.datamodel or not self.datamodel.project:
            raise CommandError(_("No project data"), command=self)

        if not self.undo_data:
            raise UndoError(_("No undo data available"), command=self)

        subtitles : Subtitles = self.datamodel.project.subtitles

        updates = {}
        for scene_number, batch_number, original_lines, translated_lines in self.undo_data:
            batch : SubtitleBatch = subtitles.GetBatch(scene_number, batch_number)
            for line in original_lines:
                batch.AddLine(line)
                updates[(scene_number, batch_number, line.number)] = { 'start': line.start, 'end': line.end, 'text': line.text }

            for line in translated_lines:
                batch.AddTranslatedLine(line)
                updates[(scene_number, batch_number, line.number)]['translation'] = line.text

        model_update : ModelUpdate =  self.AddModelUpdate()
        model_update.lines.updates = updates

        return True
