from GuiSubtrans.Command import Command, CommandError
from GuiSubtrans.ProjectDataModel import ProjectDataModel
from GuiSubtrans.ViewModel.ViewModelUpdate import ModelUpdate
from PySubtrans.SubtitleBatch import SubtitleBatch
from PySubtrans.SubtitleProject import SubtitleProject
from PySubtrans.SubtitleValidator import SubtitleValidator
from PySubtrans.Helpers.Localization import _

import logging

class SplitBatchCommand(Command):
    def __init__(self, scene_number : int, batch_number : int, line_number : int, translation_number : int|None = None, datamodel: ProjectDataModel|None = None):
        super().__init__(datamodel)
        self.scene_number : int = scene_number
        self.batch_number : int = batch_number
        self.line_number : int = line_number
        self.translation_number : int|None = translation_number

    def execute(self) -> bool:
        logging.info(_("Splitting scene {scene} batch: {batch} at line {line}").format(scene=str(self.scene_number), batch=str(self.batch_number), line=self.line_number))

        if not self.datamodel or not self.datamodel.project:
            raise CommandError(_("No project data"), command=self)

        project : SubtitleProject = self.datamodel.project

        if not project.subtitles:
            raise CommandError(_("No subtitles"), command=self)

        scene = project.subtitles.GetScene(self.scene_number)

        split_batch : SubtitleBatch|None = scene.GetBatch(self.batch_number) if scene else None

        if not split_batch:
            raise CommandError(_("Cannot find scene {scene} batch {batch}").format(scene=self.scene_number, batch=self.batch_number), command=self)

        scene.SplitBatch(self.batch_number, self.line_number, self.translation_number)

        new_batch_number = self.batch_number + 1

        split_batch = scene.GetBatch(self.batch_number)
        new_batch : SubtitleBatch|None = scene.GetBatch(new_batch_number)

        if not new_batch:
            raise CommandError(_("Failed to create new batch after splitting"), command=self)

        if split_batch is not None and (split_batch.any_translated or new_batch.any_translated):
            validator = SubtitleValidator(self.datamodel.project_options)
            validator.ValidateBatch(split_batch)
            validator.ValidateBatch(new_batch)

        if split_batch is not None and new_batch is not None and new_batch.last_line_number is not None:
            # Remove lines from the original batch that are in the new batch now
            model_update : ModelUpdate =  self.AddModelUpdate()
            for line_removed in range(self.line_number, new_batch.last_line_number + 1):
                model_update.lines.remove((self.scene_number, self.batch_number, line_removed))

            for batch_number in range(self.batch_number + 1, len(scene.batches)):
                model_update.batches.update((self.scene_number, batch_number), { 'number' : batch_number + 1})

            model_update.batches.update((self.scene_number, self.batch_number), { 'errors' : split_batch.errors })
            new_batch = scene.GetBatch(new_batch_number)
            if new_batch is not None:
                model_update.batches.add((self.scene_number, new_batch_number), new_batch)

        return True

    def undo(self):
        if not self.datamodel or not self.datamodel.project:
            raise CommandError(_("No project data"), command=self)

        project: SubtitleProject = self.datamodel.project

        if not project.subtitles:
            raise CommandError(_("No subtitles"), command=self)

        scene = project.subtitles.GetScene(self.scene_number)

        if not scene or not scene.GetBatch(self.batch_number):
            raise CommandError(_("Cannot find scene {scene} batch {batch}").format(scene=self.scene_number, batch=self.batch_number), command=self)

        try:
            scene.MergeBatches([self.batch_number, self.batch_number + 1])

            removed_batch_number = self.batch_number + 1

            model_update : ModelUpdate =  self.AddModelUpdate()
            batch = scene.GetBatch(self.batch_number)
            if batch is not None:
                model_update.batches.replace((self.scene_number, self.batch_number), batch)
            model_update.batches.remove((self.scene_number, removed_batch_number))

            return True

        except Exception as e:
            self.ClearModelUpdates()
            raise CommandError(_("Unable to undo SplitBatchCommand command: {error}").format(error=str(e)), command=self)
