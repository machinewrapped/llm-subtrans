from GuiSubtrans.ViewModel.ViewModelUpdateSection import ModelUpdateSection
from GuiSubtrans.ViewModel.ViewModel import ProjectViewModel
from PySubtrans.SubtitleBatch import SubtitleBatch
from PySubtrans.SubtitleLine import SubtitleLine
from PySubtrans.SubtitleScene import SubtitleScene

class ModelUpdate:
    def __init__(self):
        self.scenes : ModelUpdateSection = ModelUpdateSection()
        self.batches : ModelUpdateSection = ModelUpdateSection()
        self.lines : ModelUpdateSection = ModelUpdateSection()

    def HasUpdate(self) -> bool:
        """ Returns True if there are any updates """
        return self.scenes.has_updates or self.batches.has_updates or self.lines.has_updates

    def ApplyToViewModel(self, viewmodel : ProjectViewModel):
        """ Apply the updates to the viewmodel """
        for scene_number, scene in self.scenes.replacements.items():
            if not isinstance(scene, SubtitleScene):
                raise ValueError(f"Scene replacement is not a SubtitleScene: {type(scene)}")
            viewmodel.ReplaceScene(scene)

        for scene_number, scene_update in self.scenes.updates.items():
            if not isinstance(scene_update, dict):
                raise ValueError(f"Scene update is not a dictionary: {type(scene_update)}")
            if not isinstance(scene_number, int):
                raise ValueError(f"Scene update key is not an int: {type(scene_number)}")
            viewmodel.UpdateScene(scene_number, scene_update)

        for scene_number in reversed(self.scenes.removals):
            if not isinstance(scene_number, int):
                raise ValueError(f"Scene removal is not an int: {type(scene_number)}")
            viewmodel.RemoveScene(scene_number)

        for scene_number, scene in self.scenes.additions.items():
            if not isinstance(scene, SubtitleScene):
                raise ValueError(f"Scene addition is not a SubtitleScene: {type(scene)}")
            viewmodel.AddScene(scene)

        for key, batch in self.batches.replacements.items():
            if not isinstance(batch, SubtitleBatch):
                raise ValueError(f"Batch replacement is not a SubtitleBatch: {type(batch)}")
            if not isinstance(key, tuple) or len(key) != 2:
                raise ValueError(f"Batch replacement key is not a tuple of (scene_number, batch_number): {key}")

            scene_number, batch_number = key
            viewmodel.ReplaceBatch(batch)

        for key, batch_update in self.batches.updates.items():
            if not isinstance(key, tuple) or len(key) != 2:
                raise ValueError(f"Batch update key is not a tuple of (scene_number, batch_number): {key}")
            if not isinstance(batch_update, dict):
                raise ValueError(f"Batch update is not a dict: {type(batch_update)}")

            scene_number, batch_number = key
            viewmodel.UpdateBatch(scene_number, batch_number, batch_update)

        for key in reversed(self.batches.removals):
            if not isinstance(key, tuple) or len(key) != 2:
                raise ValueError(f"Batch removal key is not a tuple of (scene_number, batch_number): {key}")
            scene_number, batch_number = key
            viewmodel.RemoveBatch(scene_number, batch_number)

        for key, batch in self.batches.additions.items():
            if not isinstance(batch, SubtitleBatch):
                raise ValueError(f"Batch addition is not a SubtitleBatch: {type(batch)}")
            if not isinstance(key, tuple) or len(key) != 2:
                raise ValueError(f"Batch addition key is not a tuple of (scene_number, batch_number): {key}")

            scene_number, batch_number = key
            viewmodel.AddBatch(batch)

        if self.lines.updates:
            batched_line_updates = self.GetUpdatedLinesInBatches()
            for key, line_updates in batched_line_updates.items():
                scene_number, batch_number = key
                viewmodel.UpdateLines(scene_number, batch_number, line_updates)

        if self.lines.removals:
            batched_line_removals = self.GetRemovedLinesInBatches()
            for key, line_numbers in batched_line_removals.items():
                scene_number, batch_number = key
                viewmodel.RemoveLines(scene_number, batch_number, line_numbers)

        for key, line in self.lines.additions.items():
            if not isinstance(line, SubtitleLine):
                raise ValueError(f"Line addition is not a SubtitleLine: {type(line)}")
            if not isinstance(key, tuple) or len(key) != 3:
                raise ValueError(f"Line addition key is not a tuple of (scene_number, batch_number, line_number): {key}")
            scene_number, batch_number, line_number = key
            if line_number != line.number:
                raise ValueError(f"Line number mismatch: {line_number} != {line.number}")
            viewmodel.AddLine(scene_number, batch_number, line)

    def GetRemovedLinesInBatches(self):
        """
        Returns a dictionary of removed lines in batches.

        returns:
            dict: The key is a tuple of (scene_number, batch_number) and the value is a list of line numbers.
        """
        batches = {}
        for key in self.lines.removals:
            if not isinstance(key, tuple) or len(key) != 3:
                raise ValueError(f"Line removal key is not a tuple of (scene_number, batch_number, line_number): {key}")

            scene_number, batch_number, line_number = key
            key = (scene_number, batch_number)
            if key not in batches:
                batches[key] = [ line_number ]
            else:
                batches[key].append(line_number)

        return batches

    def GetUpdatedLinesInBatches(self):
        """
        Returns a dictionary of updated lines in batches.

        returns:
            dict: The key is a tuple of (scene_number, batch_number) and the value is a dictionary of line numbers and their updates.
        """
        batches = {}
        for pair in self.lines.updates.items():
            line_key, line = pair
            if not isinstance(line_key, tuple) or len(line_key) != 3:
                raise ValueError(f"Line update key is not a tuple of (scene_number, batch_number, line_number): {line_key}")

            scene_number, batch_number, line_number = line_key
            batch_key = (scene_number, batch_number)
            if batch_key in batches:
                batches[batch_key][line_number] = line
            else:
                batches[batch_key] = { line_number: line }

        return batches