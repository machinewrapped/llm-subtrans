from GuiSubtrans.Command import Command, CommandError
from GuiSubtrans.ProjectDataModel import ProjectDataModel
from GuiSubtrans.ViewModel.ViewModelUpdate import ModelUpdate
from PySubtrans.SubtitleBatch import SubtitleBatch
from PySubtrans.SubtitleProject import SubtitleProject
from PySubtrans.SubtitleValidator import SubtitleValidator
from PySubtrans.Helpers.Localization import _

import logging

class AutoSplitBatchCommand(Command):
    def __init__(self, scene_number : int, batch_number : int, datamodel: ProjectDataModel|None = None):
        super().__init__(datamodel)
        self.scene_number : int = scene_number
        self.batch_number : int= batch_number
        self.split_line : int|None = None

    def execute(self) -> bool:
        logging.info(_("Auto-splitting batch {scene} batch {batch}").format(scene=str(self.scene_number), batch=str(self.batch_number)))

        if not self.datamodel or not self.datamodel.project:
            raise CommandError("No datamodel", command=self)

        project : SubtitleProject = self.datamodel.project

        if not project.subtitles:
            raise CommandError(_("No subtitles"), command=self)

        scene = project.subtitles.GetScene(self.scene_number)

        if not scene or not scene.GetBatch(self.batch_number):
            raise CommandError(f"Cannot find scene {self.scene_number} batch {self.batch_number}", command=self)

        min_batch_size = self.datamodel.project_options.get_int('min_batch_size') or 1
        scene.AutoSplitBatch(self.batch_number, min_batch_size)

        new_batch_number = self.batch_number + 1

        split_batch : SubtitleBatch|None = scene.GetBatch(self.batch_number)
        new_batch : SubtitleBatch|None = scene.GetBatch(new_batch_number)

        if not split_batch or not new_batch:
            raise CommandError(f"Cannot find split batch {self.batch_number} or new batch {new_batch_number}", command=self)

        validator = SubtitleValidator(self.datamodel.project_options)
        validator.ValidateBatch(split_batch)
        validator.ValidateBatch(new_batch)

        if not new_batch.first_line_number or not new_batch.last_line_number:
            raise CommandError(f"New batch {new_batch_number} has no lines", command=self)

        # Remove lines from the original batch that are in the new batch now
        model_update : ModelUpdate =  self.AddModelUpdate()
        for line_removed in range(new_batch.first_line_number, new_batch.last_line_number + 1):
            model_update.lines.remove((self.scene_number, self.batch_number, line_removed))

        for batch_number in range(self.batch_number + 1, len(scene.batches)):
             model_update.batches.update((self.scene_number, batch_number), { 'number' : batch_number + 1})

        model_update.batches.update((self.scene_number, self.batch_number), { 'errors' : split_batch.error_messages })
        new_batch = scene.GetBatch(new_batch_number)
        if new_batch:
            model_update.batches.add((self.scene_number, new_batch_number), new_batch)
            self.split_line = new_batch.first_line_number

        return True

    def undo(self) -> bool:
        if not self.datamodel or not self.datamodel.project:
            raise CommandError("No datamodel", command=self)

        project: SubtitleProject = self.datamodel.project

        scene = project.subtitles.GetScene(self.scene_number)

        if not scene or not scene.GetBatch(self.batch_number):
            raise CommandError(f"Cannot find scene {self.scene_number} batch {self.batch_number}", command=self)

        scene.MergeBatches([self.batch_number, self.batch_number + 1])

        merged_batch = scene.GetBatch(self.batch_number)

        if not merged_batch:
            raise CommandError(f"Cannot find merged batch {self.batch_number}", command=self)

        model_update : ModelUpdate =  self.AddModelUpdate()
        model_update.batches.remove((self.scene_number, self.batch_number + 1))
        model_update.batches.update((self.scene_number, self.batch_number), { 'errors' : merged_batch.error_messages })

        if not self.split_line or not merged_batch.first_line_number or not merged_batch.last_line_number:
            logging.warning(f"Split line number {self.split_line} or merged batch line numbers ({merged_batch.first_line_number}, {merged_batch.last_line_number}) is not set")
            return True

        model_update : ModelUpdate =  self.AddModelUpdate()
        for line_number in range(self.split_line, merged_batch.last_line_number + 1):
            key = (self.scene_number, self.batch_number, line_number)
            line = merged_batch.GetOriginalLine(line_number)
            if line:
                line.translated = merged_batch.GetTranslatedLine(line_number)
                model_update.lines.add(key, line)
            else:
                logging.warning(f"Line {line_number} not found in merged batch {self.batch_number}")

        return True