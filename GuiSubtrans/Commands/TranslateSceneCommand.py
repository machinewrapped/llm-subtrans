from GuiSubtrans.Command import Command, CommandError
from GuiSubtrans.ProjectDataModel import ProjectDataModel
from GuiSubtrans.ViewModel.ViewModelUpdate import ModelUpdate
from PySubtrans.Helpers import FormatErrorMessages
from PySubtrans.SubtitleBatch import SubtitleBatch
from PySubtrans.SubtitleError import TranslationAbortedError, TranslationImpossibleError
from PySubtrans.SubtitleProject import SubtitleProject
from PySubtrans.SubtitleTranslator import SubtitleTranslator
from PySubtrans.Helpers.Localization import _

import logging

#############################################################

class TranslateSceneCommand(Command):
    """
    Ask the translator to translate a scene (optionally just select batches in the scene)
    """
    def __init__(self, scene_number : int,
                    batch_numbers : list[int]|None = None,
                    line_numbers : list[int]|None = None,
                    resume : bool = False,
                    datamodel : ProjectDataModel|None = None):

        super().__init__(datamodel)
        self.translator : SubtitleTranslator|None = None
        self.resume : bool = resume
        self.scene_number : int = scene_number
        self.batch_numbers : list[int]|None = batch_numbers
        self.line_numbers : list[int]|None = line_numbers
        self.can_undo = False

    def execute(self) -> bool:
        if self.batch_numbers:
            logging.info(_("Translating scene number {scene} batch {batches}").format(scene=self.scene_number, batches=','.join(str(x) for x in self.batch_numbers)))
        else:
            logging.info(_("Translating scene number {scene}").format(scene=self.scene_number))

        if not self.datamodel or not self.datamodel.project:
            raise CommandError(_("No project data"), command=self)

        project : SubtitleProject = self.datamodel.project

        if not project.subtitles:
            raise CommandError(_("No subtitles in project"), command=self)

        # Create our own translator instance for thread safety
        options = self.datamodel.project_options
        translation_provider = self.datamodel.translation_provider

        if not translation_provider:
            raise CommandError(_("No translation provider configured"), command=self)

        if not translation_provider.ValidateSettings():
            raise CommandError(_("Translation provider settings are invalid"), command=self)

        self.translator = SubtitleTranslator(options, translation_provider, resume=self.resume)

        self.translator.events.batch_translated += self._on_batch_translated # type: ignore

        try:
            scene = project.subtitles.GetScene(self.scene_number)
            scene.errors = []

            self.translator.TranslateScene(project.subtitles, scene, batch_numbers=self.batch_numbers, line_numbers=self.line_numbers)

            if scene:
                model_update : ModelUpdate =  self.AddModelUpdate()
                model_update.scenes.update(scene.number, {
                    'summary' : scene.summary
                })

            if self.translator.errors and self.translator.stop_on_error:
                logging.info(_("Errors: {errors}").format(errors=FormatErrorMessages(self.translator.errors)))
                logging.error(_("Errors translating scene {scene} - aborting translation").format(scene=scene.number if scene else self.scene_number))
                self.terminal = True

            if self.translator.aborted:
                self.aborted = True
                self.terminal = True

        except TranslationAbortedError as e:
            logging.info(_("Aborted translation of scene {scene}").format(scene=self.scene_number))
            self.aborted = True
            self.terminal = True

        except TranslationImpossibleError as e:
            logging.error(_("Error translating scene {scene}: {error}").format(scene=self.scene_number, error=e))
            self.terminal = True

        except Exception as e:
            logging.error(_("Error translating scene {scene}: {error}").format(scene=self.scene_number, error=e))
            if self.translator and self.translator.stop_on_error:
                self.terminal = True

        if self.translator:
            self.translator.events.batch_translated -= self._on_batch_translated # type: ignore

        return True

    def on_abort(self):
        if self.translator:
            self.translator.StopTranslating()

    def _on_batch_translated(self, batch : SubtitleBatch):
        # Update viewmodel as each batch is translated
        if self.datamodel and batch.translated:
            update = ModelUpdate()
            update.batches.update((batch.scene, batch.number), {
                'summary' : batch.summary,
                'context' : batch.context,
                'errors' : batch.error_messages,
                'translation': batch.translation,
                'prompt': batch.prompt,
                'lines' : { line.number : { 'translation' : line.text } for line in batch.translated if line.number }
            })

            self.datamodel.UpdateViewModel(update)

