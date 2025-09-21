from GuiSubtrans.Command import Command, CommandError
from PySubtrans.Helpers.Localization import _
from PySubtrans.SubtitleProject import SubtitleProject

class SaveProjectFile(Command):
    def __init__(self, project : SubtitleProject, filepath : str|None = None):
        super().__init__()
        self.can_undo = False
        self.is_blocking = True
        self.mark_project_dirty = False
        self.project : SubtitleProject = project
        self.filepath : str|None = filepath or project.projectfile

    def execute(self) -> bool:
        if not self.filepath:
            raise CommandError(_("Project file path must be specified."), command=self)

        if not self.datamodel or not self.datamodel.project:
            raise CommandError(_("No project data"), command=self)

        current_filepath = self.datamodel.project.projectfile
        current_outputpath = self.datamodel.project.subtitles.outputpath

        # Update the project path and set the subtitle output path to the same location
        self.project.projectfile = self.project.GetProjectFilepath(self.filepath)
        self.project.UpdateOutputPath(path=self.project.projectfile, extension=self.project.subtitles.file_format)

        if current_filepath != self.project.projectfile or current_outputpath != self.project.subtitles.outputpath:
            self.project.needs_writing = True

        self.project.SaveProject()

        return True
