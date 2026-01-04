from GuiSubtrans.Command import Command
from PySubtrans.Helpers.Localization import _
from PySubtrans.SubtitleProject import SubtitleProject

class SaveSubtitleFile(Command):
    def __init__(self, filepath, project : SubtitleProject):
        super().__init__()
        self.filepath = filepath
        self.project = project
        self.mark_project_dirty = False
        self.skip_undo = True

    def execute(self) -> bool:
        self.project.SaveOriginal(self.filepath)
        return True