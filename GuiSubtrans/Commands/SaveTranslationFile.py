import logging

from GuiSubtrans.Command import Command, CommandError
from PySubtrans.Helpers.Localization import _
from PySubtrans.SubtitleFormatRegistry import SubtitleFormatRegistry
from PySubtrans.SubtitleProject import SubtitleProject

class SaveTranslationFile(Command):
    def __init__(self, project : SubtitleProject, filepath : str|None = None):
        super().__init__()
        self.filepath = filepath or project.subtitles.outputpath
        self.project = project
        self.skip_undo = True
        self.mark_project_dirty = False

    def execute(self) -> bool:
        # Validate before SaveTranslation acquires the project lock.
        try:
            SubtitleFormatRegistry.create_handler(filename=self.filepath)
        except ValueError as error:
            raise CommandError(str(error), command=self) from error

        # Nothing to save before translation (e.g. a fresh transcription):
        # skip quietly instead of erroring on every autosave tick.
        if not self.project.any_translated:
            logging.info(_("No translations to save yet"))
            return True

        self.project.SaveTranslation(self.filepath)
        return True