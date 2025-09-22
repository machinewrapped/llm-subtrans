from datetime import timedelta
import logging
from copy import deepcopy
from math import e
from GuiSubtrans.Command import Command, CommandError
from GuiSubtrans.ProjectDataModel import ProjectDataModel
from GuiSubtrans.ViewModel.ViewModelUpdate import ModelUpdate
from PySubtrans.Helpers.Time import GetTimeDelta
from PySubtrans.SubtitleBatch import SubtitleBatch
from PySubtrans.SubtitleLine import SubtitleLine
from PySubtrans.SubtitleEditor import SubtitleEditor
from PySubtrans.Subtitles import Subtitles

from PySubtrans.SubtitleValidator import SubtitleValidator
from PySubtrans.Helpers.Localization import _

class EditLineCommand(Command):
    def __init__(self, line_number : int, edit : dict, datamodel : ProjectDataModel|None = None):
        super().__init__(datamodel)
        self.line_number : int = line_number
        self.edit : dict = deepcopy(edit)
        self.undo_data : dict|None = None

    def execute(self) -> bool:
        logging.debug(_("Editing line {line}").format(line=self.line_number))

        if not self.datamodel or not self.datamodel.project:
            raise CommandError(_("No project data"), command=self)

        subtitles : Subtitles = self.datamodel.project.subtitles
        if not subtitles:
            raise CommandError(_("Unable to edit batch because datamodel is invalid"), command=self)

        if not isinstance(self.edit, dict):
            raise CommandError(_("Edit data must be a dictionary"), command=self)

        with SubtitleEditor(subtitles) as editor:
            batch : SubtitleBatch|None = subtitles.GetBatchContainingLine(self.line_number)
            if not batch:
                raise CommandError(_("Line {line} not found in any batch").format(line=self.line_number), command=self)

            line : SubtitleLine|None = batch.GetOriginalLine(self.line_number)
            if not line:
                raise CommandError(_("Line {line} not found in batch ({scene},{batch})").format(line=self.line_number, scene=batch.scene, batch=batch.number), command=self)

            # Store undo data before making changes
            self.undo_data = {
                key: getattr(line, key)
                for key in ['start', 'end', 'text']
                if key in self.edit
            }

            if 'translation' in self.edit:
                translated_line = batch.GetTranslatedLine(self.line_number)
                self.undo_data['translation'] = translated_line.text if translated_line else line.translation

            # Handle metadata separately to track additions and removals
            if 'metadata' in self.edit:
                self.undo_data['metadata'] = {}
                # Store existing values (or None for new keys that need removal on undo)
                for key in self.edit['metadata'].keys():
                    self.undo_data['metadata'][key] = line.metadata.get(key)

            try:
                editor.UpdateLine(self.line_number, self.edit)
            except ValueError as e:
                raise CommandError(str(e), command=self)

            self._update_model(batch, line)

        return True

    def undo(self):
        logging.debug(_("Undoing edit line {line}").format(line=self.line_number))

        if not self.datamodel or not self.datamodel.project:
            raise CommandError(_("No project data"), command=self)

        if not self.undo_data:
            raise CommandError(_("No undo data available"), command=self)

        subtitles : Subtitles = self.datamodel.project.subtitles

        with SubtitleEditor(subtitles) as editor:
            batch : SubtitleBatch|None = subtitles.GetBatchContainingLine(self.line_number)
            if not batch:
                raise CommandError(_("Line {line} not found in any batch").format(line=self.line_number), command=self)

            line : SubtitleLine|None = batch.GetOriginalLine(self.line_number)
            if not line:
                raise CommandError(_("Line {line} not found in batch ({scene},{batch})").format(line=self.line_number, scene=batch.scene, batch=batch.number), command=self)

            try:
                editor.UpdateLine(self.line_number, self.undo_data)
            except ValueError as e:
                raise CommandError(str(e), command=self)

            self._update_model(batch, line)

        return True

    def _update_model(self, batch : SubtitleBatch, line : SubtitleLine):
        viewmodel_update : ModelUpdate = self.AddModelUpdate()
        viewmodel_update.lines.update((batch.scene, batch.number, self.line_number), {
                                            'start': line.txt_start,
                                            'end': line.txt_end,
                                            'text': line.text,
                                            'translation': line.translation
                                            })

        if self.datamodel:
            validator = SubtitleValidator(self.datamodel.project_options)
            self.errors = validator.ValidateBatch(batch)
            viewmodel_update.batches.update((batch.scene,batch.number), { 'errors': self.errors })

