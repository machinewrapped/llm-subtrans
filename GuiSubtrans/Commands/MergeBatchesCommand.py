from GuiSubtrans.Command import Command, CommandError
from GuiSubtrans.ProjectDataModel import ProjectDataModel
from GuiSubtrans.ViewModel.ViewModelUpdate import ModelUpdate
from PySubtrans.Helpers.Localization import _
from PySubtrans.SubtitleBatch import SubtitleBatch
from PySubtrans.SubtitleProject import SubtitleProject

import logging

from PySubtrans.SubtitleValidator import SubtitleValidator

class MergeBatchesCommand(Command):
    """
    Combine multiple batches into one
    """
    def __init__(self, scene_number: int, batch_numbers: list[int], datamodel: ProjectDataModel|None = None):
        super().__init__(datamodel)
        self.scene_number : int = scene_number
        self.batch_numbers : list[int] = sorted(batch_numbers)
        self.original_first_line_numbers : list[int] = []
        self.original_summaries : dict[int, str] = {}

    def execute(self) -> bool:
        logging.info(f"Merging scene {str(self.scene_number)} batches: {','.join(str(x) for x in self.batch_numbers)}")

        if not self.datamodel or not self.datamodel.project:
            raise CommandError(_("No project data"), command=self)

        project: SubtitleProject = self.datamodel.project
        scene = project.subtitles.GetScene(self.scene_number)

        if len(self.batch_numbers) > 1:
            merged_batch_number = self.batch_numbers[0]

            original_batches = [scene.GetBatch(batch_number) for batch_number in self.batch_numbers]

            if any(b is None or b.scene != scene.number or b.first_line_number is None or b.last_line_number is None for b in original_batches):
                raise CommandError(_("Invalid batch"), command=self)

            self.original_first_line_numbers = [batch.first_line_number for batch in original_batches if batch and batch.first_line_number]
            self.original_summaries = {batch.number: batch.summary for batch in original_batches if batch and batch.summary}

            project.subtitles.MergeBatches(self.scene_number, self.batch_numbers)

            merged_batch = scene.GetBatch(merged_batch_number)
            if merged_batch is not None:
                if merged_batch.any_translated:
                    validator = SubtitleValidator(self.datamodel.project_options)
                    validator.ValidateBatch(merged_batch)

                model_update : ModelUpdate =  self.AddModelUpdate()
                model_update.batches.replace((scene.number, merged_batch_number), merged_batch)
                for batch_number in self.batch_numbers[1:]:
                    model_update.batches.remove((scene.number, batch_number))

        return True

    def undo(self):
        if not self.datamodel or not self.datamodel.project:
            raise CommandError(_("No project data"), command=self)

        project: SubtitleProject = self.datamodel.project
        scene = project.subtitles.GetScene(self.scene_number)

        # Split the merged batch back into the original batches using the stored first line numbers
        for i in range(0, len(self.batch_numbers) - 1):
            scene.SplitBatch(self.batch_numbers[i], self.original_first_line_numbers[i+1])

        # Restore the original summaries
        for batch_number, summary in self.original_summaries.items():
            batch : SubtitleBatch|None = scene.GetBatch(batch_number)
            if batch:
                batch.summary = summary

        model_update : ModelUpdate =  self.AddModelUpdate()
        model_update.scenes.replace(scene.number, scene)

        return True