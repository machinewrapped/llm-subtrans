import logging

from GuiSubtrans.Command import Command, CommandError, UndoError
from GuiSubtrans.ProjectDataModel import ProjectDataModel
from GuiSubtrans.ViewModel.ViewModelUpdate import ModelUpdate
from PySubtrans.Helpers.Localization import _
from PySubtrans.SubtitleBatch import SubtitleBatch
from PySubtrans.SubtitleProject import SubtitleProject
from PySubtrans.Subtitles import Subtitles

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

        project: SubtitleProject = self.datamodel.project
        subtitles : Subtitles = project.subtitles

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

            with project.GetEditor() as editor:
                merged_line, merged_translated = editor.MergeLinesInBatch(batch.scene, batch.number, batch_lines)

            if not merged_line:
                raise CommandError(_("Failed to merge lines"), command=self)

            line_update = {
                'start': merged_line.txt_start,
                'end': merged_line.txt_end,
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

        model_update : ModelUpdate = self.AddModelUpdate()
        for scene_number, batch_number, original_lines, translated_lines in self.undo_data:
            batch : SubtitleBatch = subtitles.GetBatch(scene_number, batch_number)
            translated_by_number = { line.number: line for line in translated_lines }

            for line_index, line in enumerate(original_lines):
                batch.AddLine(line)

                translated_line = translated_by_number.get(line.number)
                line_update = {
                    'start': line.txt_start,
                    'end': line.txt_end,
                    'text': line.text,
                    'translation': translated_line.text if translated_line else None,
                }

                if line_index == 0:
                    # The first line survived the merge and can be patched in place.
                    model_update.lines.update((scene_number, batch_number, line.number), line_update)
                else:
                    # All following lines were removed from the view model and must be added back.
                    restored_line = line.copy()
                    restored_line.translation = translated_line.text if translated_line else None
                    model_update.lines.add((scene_number, batch_number, line.number), restored_line)

            for translated_line in translated_lines:
                batch.AddTranslatedLine(translated_line)

        return True
