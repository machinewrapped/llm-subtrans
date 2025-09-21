from copy import deepcopy
import logging
from typing import TYPE_CHECKING

from GuiSubtrans.Command import Command, CommandError
from GuiSubtrans.Commands.SaveProjectFile import SaveProjectFile
from GuiSubtrans.ProjectDataModel import ProjectDataModel
from PySubtrans.Helpers import GetOutputPath
from PySubtrans.Helpers.Localization import _
from PySubtrans.Options import Options
from PySubtrans.SubtitleBatcher import SubtitleBatcher
from PySubtrans.SubtitleProcessor import SubtitleProcessor
from PySubtrans.SubtitleProject import SubtitleProject

if TYPE_CHECKING:
    from PySubtrans.SubtitleEditor import SubtitleEditor

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

        with project.GetEditor() as editor:
            if self.preprocess_subtitles:
                originals = deepcopy(project.subtitles.originals)
                preprocessor = SubtitleProcessor(self.options)
                editor.PreProcess(preprocessor)

                if self.options.get('save_preprocessed', False):
                    changed = len(originals) != len(project.subtitles.originals) or any(o != n for o, n in zip(originals, project.subtitles.originals))
                    if changed:
                        output_path = GetOutputPath(project.subtitles.sourcepath, "preprocessed", project.subtitles.file_format)
                        logging.info(f"Saving preprocessed subtitles to {output_path}")
                        project.SaveOriginal(output_path)

            batcher : SubtitleBatcher = SubtitleBatcher(self.options)
            editor.AutoBatch(batcher)

        if project.use_project_file:
            self.commands_to_queue.append(SaveProjectFile(project=project))

        self.datamodel = ProjectDataModel(project, self.options)
        self.datamodel.CreateViewModel()
        return True

