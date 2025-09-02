from GUI.Command import Command, CommandError
from PySubtitle.Helpers import GetOutputPath
from PySubtitle.Helpers.Localization import _
from PySubtitle.SubtitleProject import SubtitleProject

class SaveProjectFile(Command):
    def __init__(self, project : SubtitleProject, filepath : str|None = None):
        super().__init__()
        self.can_undo = False
        self.is_blocking = True
        self.project : SubtitleProject = project
        self.filepath : str|None = filepath or project.projectfile

    def execute(self) -> bool:
        if not self.filepath:
            raise CommandError(_("Project file path must be specified."), command=self)

        if not self.datamodel or not self.datamodel.project:
            raise CommandError(_("No project data"), command=self)

        current_filepath = self.datamodel.project.projectfile
        current_outputpath = self.datamodel.project.subtitles.outputpath

        self.project.projectfile = self.project.GetProjectFilepath(self.filepath)
        self.project.subtitles.outputpath = GetOutputPath(self.project.projectfile, self.project.target_language)

        if current_filepath != self.project.projectfile or current_outputpath != self.project.subtitles.outputpath:
            self.project.needs_writing = True

        self.datamodel.SaveProject()

        return True
