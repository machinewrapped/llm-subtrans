from GuiSubtrans.Command import Command
from PySubtrans.SubtitleProject import SubtitleProject

class SaveTranslationFile(Command):
    def __init__(self, project : SubtitleProject, filepath : str|None = None):
        super().__init__()
        self.filepath = filepath or project.subtitles.outputpath
        self.project = project
        self.can_undo = False
        self.mark_project_dirty = False

    def execute(self) -> bool:
        self.project.SaveTranslation(self.filepath)
        return True