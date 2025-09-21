import logging
from typing import TYPE_CHECKING

from GuiSubtrans.Command import Command, CommandError, UndoError
from GuiSubtrans.ProjectDataModel import ProjectDataModel
from GuiSubtrans.ViewModel.ViewModelUpdate import ModelUpdate
from PySubtrans.Helpers.Localization import _
from PySubtrans.Subtitles import Subtitles

if TYPE_CHECKING:
    from PySubtrans.SubtitleEditor import SubtitleEditor

class MergeScenesCommand(Command):
    """
    Combine multiple scenes into one
    """
    def __init__(self, scene_numbers : list[int], datamodel: ProjectDataModel|None = None):
        super().__init__(datamodel)
        self.scene_numbers : list[int] = sorted(scene_numbers)
        self.scene_sizes : list[int] = []
        self.original_summaries : dict[int, str|None] = {}

    def execute(self) -> bool:
        logging.info(_("Merging scenes {scenes}").format(scenes=','.join(str(x) for x in self.scene_numbers)))

        if not self.datamodel or not self.datamodel.project:
            raise CommandError(_("No project data"), command=self)

        project = self.datamodel.project
        subtitles : Subtitles = project.subtitles

        if len(self.scene_numbers) < 2:
            raise CommandError(_("Cannot merge less than two scenes"), command=self)

        scenes_to_merge = [ subtitles.GetScene(scene_number) for scene_number in self.scene_numbers ]
        self.scene_sizes = [ scene.size for scene in scenes_to_merge ]
        self.original_summaries = { scene.number: scene.summary for scene in scenes_to_merge }

        later_scenes = [scene.number for scene in subtitles.scenes if scene.number > self.scene_numbers[-1]]

        with project.GetEditor() as editor:
            merged_scene = editor.MergeScenes(self.scene_numbers)

        model_update : ModelUpdate =  self.AddModelUpdate()
        for new_number, current_number in enumerate(later_scenes, start=merged_scene.number + 1):
            model_update.scenes.update(current_number, { 'number' : new_number })

        model_update.scenes.replace(merged_scene.number, merged_scene)
        model_update.scenes.removals = self.scene_numbers[1:]

        return True

    def undo(self):
        """
        Split the scene recursively using the saved scene sizes
        """
        if not self.scene_sizes:
            raise UndoError(_("Cannot undo merge, scene sizes were not saved"), command=self)

        if not self.datamodel or not self.datamodel.project:
            raise CommandError(_("No project data"), command=self)

        project = self.datamodel.project
        subtitles : Subtitles = project.subtitles

        model_update : ModelUpdate =  self.AddModelUpdate()

        # Remove the previously merged batches from the merged scene
        scene_to_split = subtitles.GetScene(self.scene_numbers[0])
        for batch_number in [batch.number for batch in scene_to_split.batches[self.scene_sizes[0]:]]:
            model_update.batches.remove((scene_to_split.number, batch_number))

        # Restore the original summary
        scene_to_split.summary = self.original_summaries.get(scene_to_split.number, None)
        model_update.scenes.update(scene_to_split.number, { 'summary' : scene_to_split.summary })

        # Renumber later scenes to their original numbers
        later_scenes = [scene.number for scene in subtitles.scenes if scene.number > self.scene_numbers[0]]
        later_scene_start_number = self.scene_numbers[-1] + 1
        for scene_number, current_number in enumerate(later_scenes, start=later_scene_start_number):
            model_update.scenes.update(current_number, { 'number' : scene_number })

        # Split the merged scene according to the saved scene sizes and add the new scenes to the viewmodel
        with project.GetEditor() as editor:
            for scene_number, scene_size in enumerate(self.scene_sizes[:-1], start=self.scene_numbers[0]):
                editor.SplitScene(scene_number, scene_size + 1)

                new_scene = subtitles.GetScene(scene_number + 1)
                if new_scene.number in self.original_summaries:
                    new_scene.summary = self.original_summaries.get(new_scene.number, None)

                model_update.scenes.add(scene_number + 1, new_scene)

        return True
