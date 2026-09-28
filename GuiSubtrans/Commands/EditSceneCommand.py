import logging
from copy import deepcopy
from GuiSubtrans.Command import Command, CommandError
from GuiSubtrans.ProjectDataModel import ProjectDataModel
from GuiSubtrans.ViewModel.ViewModelUpdate import ModelUpdate
from PySubtrans.Helpers.Localization import _
from PySubtrans.Subtitles import Subtitles
from PySubtrans.SubtitleScene import SubtitleScene

class EditSceneCommand(Command):
    def __init__(self, scene_number : int, edit : dict, datamodel : ProjectDataModel|None = None):
        super().__init__(datamodel)
        self.scene_number = scene_number
        self.edit = deepcopy(edit)
        self.undo_data = None

    def execute(self) -> bool:
        logging.debug(f"Editing scene {self.scene_number}")

        if not self.datamodel or not self.datamodel.project:
            raise CommandError(_("No project data"), command=self)

        subtitles : Subtitles = self.datamodel.project.subtitles
        if not subtitles:
            raise CommandError("Unable to edit scene because datamodel is invalid", command=self)

        if not isinstance(self.edit, dict):
            raise CommandError("Edit data must be a dictionary", command=self)

        with subtitles.lock:
            scene : SubtitleScene = subtitles.GetScene(self.scene_number)
            if not scene:
                raise CommandError(f"Scene {self.scene_number} not found", command=self)

            self.undo_data = {
                "summary": scene.summary,
            }

            scene.summary = self.edit.get('summary', scene.summary)

            self._update_viewmodel(scene)

        return True

    def undo(self):
        logging.debug(f"Undoing edit scene {self.scene_number}")

        if not self.datamodel or not self.datamodel.project:
            raise CommandError(_("No project data"), command=self)

        if not self.undo_data:
            raise CommandError(_("No undo data available"), command=self)

        subtitles : Subtitles = self.datamodel.project.subtitles

        with subtitles.lock:
            scene = subtitles.GetScene(self.scene_number)
            if not scene:
                raise CommandError(f"Scene {self.scene_number} not found", command=self)

            scene.summary = self.undo_data.get('summary', scene.summary)

            self._update_viewmodel(scene)

        return True

    def _update_viewmodel(self, scene : SubtitleScene):
        viewmodel_update : ModelUpdate = self.AddModelUpdate()
        viewmodel_update.scenes.update(self.scene_number, { 'summary': scene.summary })
