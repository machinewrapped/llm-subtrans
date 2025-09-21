import logging
from typing import TYPE_CHECKING

from GuiSubtrans.Command import Command, CommandError
from GuiSubtrans.ProjectDataModel import ProjectDataModel
from GuiSubtrans.ViewModel.ViewModelUpdate import ModelUpdate
from PySubtrans.Helpers.Localization import _
from PySubtrans.SubtitleBatch import SubtitleBatch
from PySubtrans.SubtitleLine import SubtitleLine
from PySubtrans.SubtitleProject import SubtitleProject
from PySubtrans.SubtitleValidator import SubtitleValidator

if TYPE_CHECKING:
    from PySubtrans.SubtitleEditor import SubtitleEditor

class DeleteLinesCommand(Command):
    """
    Delete one or several lines
    """
    def __init__(self, line_numbers : list[int], datamodel: ProjectDataModel|None = None):
        super().__init__(datamodel)
        self.line_numbers : list[int] = line_numbers
        self.deletions : list[tuple[int, int, list[SubtitleLine], list[SubtitleLine]]] = []

    def execute(self) -> bool:
        if not self.line_numbers:
            raise CommandError(_("No lines selected to delete"), command=self)

        logging.info(_("Deleting lines {lines}").format(lines=str(self.line_numbers)))

        if not self.datamodel or not self.datamodel.project:
            raise CommandError(_("No project data"), command=self)

        project : SubtitleProject = self.datamodel.project

        if not project.subtitles:
            raise CommandError(_("No subtitles"), command=self)

        with project.GetEditor() as editor:
            self.deletions = editor.DeleteLines(self.line_numbers)

        if not self.deletions:
            raise CommandError(_("No lines were deleted"), command=self)

        # Update the viewmodel. Priginal and translated lines are currently linked, deleting one means deleting both
        model_update : ModelUpdate = self.AddModelUpdate()
        for deletion in self.deletions:
            scene_number, batch_number, originals, translated = deletion # type: ignore[unused-ignore]
            for line in originals:
                model_update.lines.remove((scene_number, batch_number, line.number))

            batch = project.subtitles.GetBatch(scene_number, batch_number)
            if batch.errors:
                validator = SubtitleValidator(self.datamodel.project_options)
                validator.ValidateBatch(batch)
                model_update.batches.update((scene_number, batch_number), {'errors': batch.error_messages})

        return True

    def undo(self):
        if not self.deletions:
            raise CommandError(_("No deletions to undo"), command=self)
        
        if not self.datamodel or not self.datamodel.project:
            raise CommandError(_("No project data"), command=self)

        logging.info(_("Restoring deleted lines"))
        project : SubtitleProject = self.datamodel.project
        subtitles = project.subtitles

        model_update : ModelUpdate =  self.AddModelUpdate()

        for scene_number, batch_number, deleted_originals, deleted_translated in self.deletions:
            batch : SubtitleBatch = subtitles.GetBatch(scene_number, batch_number)
            batch.InsertLines(deleted_originals, deleted_translated)

            for line in deleted_originals:
                translated : SubtitleLine|None = next((translated for translated in deleted_translated if translated.number == line.number), None)
                if translated:
                    line.translated = translated

                model_update.lines.add((scene_number, batch_number, line.number), line)

        return True
