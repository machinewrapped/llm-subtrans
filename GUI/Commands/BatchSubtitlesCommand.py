from copy import deepcopy
from GUI.Command import Command, CommandError
from GUI.Commands.SaveProjectFile import SaveProjectFile
from GUI.ProjectDataModel import ProjectDataModel
from PySubtitle.Helpers import GetOutputPath
from PySubtitle.Helpers.Localization import _
from PySubtitle.Options import Options
from PySubtitle.SubtitleBatcher import SubtitleBatcher
from PySubtitle.SubtitleProcessor import SubtitleProcessor
from PySubtitle.SubtitleProject import SubtitleProject

import logging

class BatchSubtitlesCommand(Command):
    """
    Attempt to partition subtitles into scenes and batches based on thresholds and limits.
    """
    def __init__(self, project : SubtitleProject, options : Options):
        super().__init__()
        self.project : SubtitleProject = project
        self.options : Options = options
        self.preprocess_subtitles : bool = options.get_bool('preprocess_subtitles', False)
        self.can_undo = False

    def execute(self) -> bool:
        logging.info("Executing BatchSubtitlesCommand")

        project : SubtitleProject = self.project

        if not project or not project.subtitles or not project.subtitles.originals:
            raise CommandError(_("No subtitles to batch"), command=self)

        if self.preprocess_subtitles:
            originals = deepcopy(project.subtitles.originals)
            preprocessor = SubtitleProcessor(self.options)
            project.subtitles.PreProcess(preprocessor)

            if self.options.get('save_preprocessed', False):
                changed = len(originals) != len(project.subtitles.originals) or any(o != n for o, n in zip(originals, project.subtitles.originals))
                if changed:
                    output_path = GetOutputPath(project.projectfile, "preprocessed")
                    logging.info(f"Saving preprocessed subtitles to {output_path}")
                    project.SaveOriginal(output_path)

        batcher : SubtitleBatcher = SubtitleBatcher(self.options)
        project.subtitles.AutoBatch(batcher)

        if project.use_project_file:
            self.commands_to_queue.append(SaveProjectFile(project=project))

        self.datamodel = ProjectDataModel(project, self.options)
        self.datamodel.CreateViewModel()
        return True

