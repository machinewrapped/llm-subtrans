from GUI.Command import Command, CommandError
from PySubtitle.Helpers.Localization import _
from PySubtitle.SubtitleProject import SubtitleProject

class SaveSubtitleFile(Command):
    def __init__(self, filepath, project : SubtitleProject):
        super().__init__()
        self.filepath = filepath
        self.project = project

    def execute(self) -> bool:
        self.project.SaveOriginal(self.filepath)
        return True