from GuiSubtrans.Command import Command
from PySubtrans.Subtitles import Subtitles


class SaveSubtitleFile(Command):
    """
    Write original subtitles to a subtitle file.
    """
    def __init__(self, filepath : str, subtitles : Subtitles):
        super().__init__()
        self.filepath = filepath
        self.subtitles = subtitles
        self.mark_project_dirty = False
        self.skip_undo = True
        # This writes a subtitle snapshot and must not affect the active project model.
        self.updates_datamodel = False

    def execute(self) -> bool:
        self.subtitles.SaveOriginal(self.filepath)
        return True
