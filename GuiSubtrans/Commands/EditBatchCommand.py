from copy import deepcopy
from GuiSubtrans.Command import Command, CommandError
from GuiSubtrans.ProjectDataModel import ProjectDataModel
from GuiSubtrans.ViewModel.ViewModelUpdate import ModelUpdate
from GuiSubtrans.ViewModel.ViewModelUpdateSection import UpdateValue
from PySubtrans.SubtitleBatch import SubtitleBatch
from PySubtrans.Subtitles import Subtitles

import logging
from PySubtrans.Helpers.Localization import _

class EditBatchCommand(Command):
    def __init__(self, scene_number : int, batch_number : int, edit : dict[str, UpdateValue], datamodel : ProjectDataModel|None = None):
        super().__init__(datamodel)
        self.scene_number = scene_number
        self.batch_number = batch_number
        self.edit : dict[str, UpdateValue] = deepcopy(edit)
        self.undo_data = None

    def execute(self) -> bool:
        logging.debug(_("Editing batch ({scene},{batch})").format(scene=self.scene_number, batch=self.batch_number))

        if not self.datamodel or not self.datamodel.project:
            raise CommandError(_("No project data"), command=self)

        subtitles : Subtitles = self.datamodel.project.subtitles
        if not subtitles:
            raise CommandError(_("Unable to edit batch because datamodel is invalid"), command=self)

        if not isinstance(self.edit, dict):
            raise CommandError(_("Edit data must be a dictionary"), command=self)

        with subtitles.lock:
            batch : SubtitleBatch = subtitles.GetBatch(self.scene_number, self.batch_number)
            if not batch:
                raise CommandError(_("Batch ({scene},{batch}) not found").format(scene=self.scene_number, batch=self.batch_number), command=self)

            self.undo_data = {
                "summary": batch.summary,
            }

            edit_summary : UpdateValue = self.edit.get('summary')
            if isinstance(edit_summary, str):
                batch.summary = edit_summary

            self._update_viewmodel(batch)

        return True

    def undo(self):
        logging.debug(_("Undoing edit batch ({scene},{batch})").format(scene=self.scene_number, batch=self.batch_number))

        if not self.datamodel or not self.datamodel.project:
            raise CommandError(_("No project data"), command=self)

        if not self.undo_data:
            raise CommandError(_("No undo data available"), command=self)

        subtitles : Subtitles = self.datamodel.project.subtitles

        with subtitles.lock:
            batch : SubtitleBatch = subtitles.GetBatch(self.scene_number, self.batch_number)
            if not batch:
                raise CommandError(_("Batch ({scene},{batch}) not found").format(scene=self.scene_number, batch=self.batch_number), command=self)

            batch.summary = self.undo_data.get('summary', batch.summary)

            self._update_viewmodel(batch)

        return True

    def _update_viewmodel(self, batch : SubtitleBatch):
        viewmodel_update : ModelUpdate = self.AddModelUpdate()
        viewmodel_update.batches.update((self.scene_number, self.batch_number), { 'summary': batch.summary })

