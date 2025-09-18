from GuiSubtrans.Command import Command, CommandError
from GuiSubtrans.ProjectDataModel import ProjectDataModel
from GuiSubtrans.ViewModel.ViewModelUpdate import ModelUpdate
from GuiSubtrans.ViewModel.ViewModelUpdateSection import BatchKey, LineKey, UpdateValue
from PySubtrans.Options import Options
from PySubtrans.SubtitleBatch import SubtitleBatch
from PySubtrans.Subtitles import Subtitles
from PySubtrans.SubtitleProject import SubtitleProject
from PySubtrans.SubtitleTranslator import SubtitleTranslator
from PySubtrans.Helpers.Localization import _

import logging

from PySubtrans.SubtitleValidator import SubtitleValidator
from PySubtrans.TranslationProvider import TranslationProvider

#############################################################

class ReparseTranslationsCommand(Command):
    """
    Ask the translator to reparse the translation for selected batches
    """
    def __init__(self, batch_numbers : list[BatchKey], line_numbers : list[int], datamodel : ProjectDataModel|None = None):
        super().__init__(datamodel)
        self.batch_numbers : list[BatchKey] = batch_numbers
        self.line_numbers : list[int] = line_numbers
        self.undo_data : list[tuple[int,int,dict]] = []

    def execute(self) -> bool:
        logging.info(_("Reparse batches {batches}").format(batches=','.join(str(x) for x in self.batch_numbers)))

        if not self.datamodel or not self.datamodel.project:
            raise CommandError(_("No project data"), command=self)

        project : SubtitleProject = self.datamodel.project
        subtitles : Subtitles = project.subtitles
        options : Options = self.datamodel.project_options
        translation_provider : TranslationProvider|None = self.datamodel.translation_provider

        if translation_provider is None:
            raise CommandError(_("No translation provider available"), command=self)

        translator = SubtitleTranslator(options, translation_provider)
        validator = SubtitleValidator(options)

        for scene_number, batch_number in self.batch_numbers:
            try:
                batch : SubtitleBatch = subtitles.GetBatch(scene_number, batch_number)

                original_summary = batch.summary
                original_translations : dict[int,str|None] = { line.number : line.text for line in batch.translated if line.number is not None }

                project.ReparseBatchTranslation(translator, scene_number, batch_number, line_numbers=self.line_numbers)

                validator.ValidateBatch(batch)

                self._generate_undo_data(batch, original_summary, original_translations)

                model_update : ModelUpdate =  self.AddModelUpdate()
                model_update.batches.update((scene_number, batch_number), {
                    'summary' : str(batch.summary) if batch.summary else None,
                    'errors' : batch.error_messages,
                    'lines' : { 
                        line.number : { 'translation' : str(line.text) if line.text else None 
                             }
                            for line in batch.translated if line.number 
                            }
                })

            except Exception as e:
                raise CommandError(_("Error reparsing scene {scene} batch {batch}: {error}").format(scene=scene_number, batch=batch_number, error=e), command=self)

        return True

    def _generate_undo_data(self, batch : SubtitleBatch, original_summary : str|None, original_translations : dict[int,str|None]):
        batch_undo : dict = { 
            'summary' : None, 
            'lines' : {} 
            }

        if batch.summary != original_summary:
            batch_undo['summary'] = original_summary

        for line in batch.translated:
            original_translation = original_translations.get(line.number, None)
            if original_translation and line.text != original_translation:
                batch_undo['lines'][line.number] = original_translation

        self.undo_data.append((batch.scene, batch.number, batch_undo))

    def undo(self):
        if not self.datamodel or not self.datamodel.project:
            raise CommandError(_("No project data"), command=self)

        project : SubtitleProject = self.datamodel.project
        subtitles : Subtitles = project.subtitles
        options = self.datamodel.project_options
        validator = SubtitleValidator(options)

        for scene_number, batch_number, batch_undo_data in self.undo_data:
            batch : SubtitleBatch = subtitles.GetBatch(scene_number, batch_number)
            summary = batch_undo_data.get('summary', None)
            undo_lines = batch_undo_data['lines']

            if summary:
                batch.summary = summary

            lines_update : ModelUpdate = self.AddModelUpdate()
            for line in batch.translated:
                undo_translated : str|None = undo_lines.get(line.number, None)
                if undo_translated:
                    line.text = undo_translated
                    lines_update.lines.update((scene_number, batch_number, line.number), { 'translation' : line.text })

            validator.ValidateBatch(batch)

            model_update : ModelUpdate =  self.AddModelUpdate()
            model_update.batches.update((scene_number, batch_number), {
                'summary' : batch.summary,
                'errors' : batch.error_messages
            })

        return True