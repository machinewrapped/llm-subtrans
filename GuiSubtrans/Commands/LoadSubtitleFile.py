from GuiSubtrans.Command import Command, CommandError
from GuiSubtrans.ProjectDataModel import ProjectDataModel
from PySubtrans.Options import Options
from PySubtrans.SubtitleProject import SubtitleProject
from PySubtrans.Helpers.Localization import _

import logging

class LoadSubtitleFile(Command):
    def __init__(self, filepath, options : Options, reload_subtitles : bool = False):
        super().__init__()
        self.filepath = filepath
        self.project : SubtitleProject|None = None
        self.options : Options = Options(options)
        self.reload_subtitles = reload_subtitles
        self.write_backup = self.options.get('write_backup', False)
        self.can_undo = False
        self.mark_project_dirty = False

    def execute(self) -> bool:
        logging.debug(_("Executing LoadSubtitleFile {file}").format(file=self.filepath))

        if not self.filepath:
            raise CommandError(_("No file path specified"), command=self)

        try:
            self.options.InitialiseInstructions()

            project = SubtitleProject(persistent=self.options.use_project_file)
            project.InitialiseProject(self.filepath, reload_subtitles=self.reload_subtitles)

            if not project.subtitles:
                raise CommandError(_("Unable to load subtitles from {file}").format(file=self.filepath), command=self)

            # Write a backup if an existing project was loaded
            if self.write_backup and project.existing_project:
                logging.info(_("Saving backup copy of the project"))
                project.SaveBackupFile()

            self.project = project
            self.datamodel = ProjectDataModel(project, self.options)

            if self.datamodel.is_project_initialised:
                self.datamodel.CreateViewModel()

            return True

        except Exception as e:
            raise CommandError(_("Unable to load {file} ({error})").format(file=self.filepath, error=str(e)), command=self)
