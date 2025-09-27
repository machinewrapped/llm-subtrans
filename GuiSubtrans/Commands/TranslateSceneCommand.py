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
        self.processed_lines : set[tuple[int, int, int]] = set()  # Track (scene, batch, line) to avoid redundant updates

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

        self.translator.events.batch_translated.connect(self._on_batch_translated)
        self.translator.events.batch_updated.connect(self._on_batch_updated)
        self.translator.events.error.connect(self._on_error)
        self.translator.events.warning.connect(self._on_warning)
        self.translator.events.info.connect(self._on_info)

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

        finally:
            if self.translator:
                self.translator.events.batch_translated.disconnect(self._on_batch_translated)
                self.translator.events.batch_updated.disconnect(self._on_batch_updated)
                self.translator.events.error.disconnect(self._on_error)
                self.translator.events.warning.disconnect(self._on_warning)
                self.translator.events.info.disconnect(self._on_info)

        return True

    def on_abort(self):
        if self.translator:
            self.translator.StopTranslating()

    def _on_batch_translated(self, _sender, batch : SubtitleBatch):
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

    def _on_batch_updated(self, _sender, batch : SubtitleBatch):
        # Handle streaming updates with only new line translations (avoid redundant updates)
        if not self.datamodel or not batch.translated:
            return

        # Find lines that haven't been processed yet
        new_lines = {}
        for line in batch.translated:
            if line.number:
                line_key = (batch.scene, batch.number, line.number)
                if line_key not in self.processed_lines:
                    new_lines[line.number] = { 'translation' : line.text }
                    self.processed_lines.add(line_key)

        # Only create update if there are new lines to process
        if new_lines:
            update = ModelUpdate()
            update.batches.update((batch.scene, batch.number), {
                'lines' : new_lines
            })
            self.datamodel.UpdateViewModel(update)

    def _on_error(self, _sender, message : str):
        """Handle error events from translator"""
        logging.error(message)

    def _on_warning(self, _sender, message : str):
        """Handle warning events from translator"""
        logging.warning(message)

    def _on_info(self, _sender, message : str):
        """Handle info events from translator"""
        logging.info(message)

