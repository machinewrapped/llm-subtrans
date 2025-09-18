import logging

from GuiSubtrans.Command import Command, CommandError
from GuiSubtrans.Commands.SaveProjectFile import SaveProjectFile
from GuiSubtrans.Commands.SaveTranslationFile import SaveTranslationFile
from GuiSubtrans.ProjectDataModel import ProjectDataModel
from GuiSubtrans.Commands.TranslateSceneCommand import TranslateSceneCommand
from PySubtrans.Helpers.Localization import _

from PySubtrans.Subtitles import Subtitles
from PySubtrans.SubtitleProject import SubtitleProject

class StartTranslationCommand(Command):
    def __init__(self, datamodel: ProjectDataModel|None = None, resume : bool = False, multithreaded : bool = False, scenes : dict|None = None):
        super().__init__(datamodel)
        self.multithreaded = multithreaded
        self.skip_undo = True
        self.is_blocking = True
        self.mark_project_dirty = False
        self.resume = resume
        self.scenes = scenes or {}

    def execute(self) -> bool:
        if not self.datamodel or not self.datamodel.project or not self.datamodel.project.subtitles:
            raise CommandError(_("Nothing to translate"), command=self)

        project : SubtitleProject = self.datamodel.project
        subtitles : Subtitles = project.subtitles

        if self.resume and subtitles.scenes and all(scene.all_translated for scene in subtitles.scenes):
            logging.info(_("All scenes are fully translated"))
            return True

        starting = _("Resuming") if self.resume and project.any_translated else _("Starting")
        threaded = _("multithreaded") if self.multithreaded else _("single threaded")
        logging.info(_("{starting} {threaded} translation").format(starting=starting, threaded=threaded))

        previous_command : Command = self

        # Save the project first if it needs updating
        if project.needs_writing:
            command = SaveProjectFile(project=project)
            self.commands_to_queue.append(command)
            previous_command = command

        for scene in subtitles.scenes:
            if self.resume and scene.all_translated:
                continue

            if self.scenes and scene.number not in self.scenes:
                continue

            scene_data = self.scenes.get(scene.number, {})
            batch_numbers = scene_data.get('batches', None)
            line_numbers = scene_data.get('lines', None)

            if self.resume and scene.any_translated:
                batches = [ batch for batch in scene.batches if not batch.all_translated ]
                batch_numbers = [ batch.number for batch in batches ]

            command = TranslateSceneCommand(scene.number, batch_numbers, line_numbers, resume=self.resume, datamodel=self.datamodel)

            if self.multithreaded:
                # Queue the commands in parallel
                self.commands_to_queue.append(command)
            else:
                # Queue the commands in sequence
                previous_command.commands_to_queue.append(command)
                previous_command = command

                if self.datamodel.autosave_enabled:
                    if self.datamodel.use_project_file:
                        command.commands_to_queue.append(SaveProjectFile(project=project))
                    else:
                        command.commands_to_queue.append(SaveTranslationFile(project=project))

        return True