from itertools import groupby
from typing import TypeAlias
from PySide6.QtCore import Qt

from GuiSubtrans.ViewModel.BatchItem import BatchItem
from GuiSubtrans.ViewModel.SceneItem import SceneItem

class SelectionScene:
    Key : TypeAlias = int
    
    def __init__(self, number : int, selected : bool = True) -> None:
        self.number = number
        self.selected = selected
        self.batches : list[SelectionBatch] = []

    def __getitem__(self, index):
        return self.batches[index]

    def __setitem__(self, index, value):
        self.batches[index] = value

    def __str__(self) -> str:
        return f"scene {self.number} [*]" if self.selected else f"scene {self.number}"

    def __repr__(self) -> str:
        return str(self)

class SelectionBatch:
    Key : TypeAlias = tuple[int,int]

    def __init__(self, batch_number : tuple, selected : bool = True, translated : bool = False) -> None:
        self.scene, self.number = batch_number
        self.selected = selected
        self.translated = translated

    @property
    def key(self):
        return (self.scene, self.number)

    def __str__(self) -> str:
        str = f"scene {self.scene}:batch {self.number}"
        return f"{str} [*]" if self.selected else str

    def __repr__(self) -> str:
        return str(self)

class SelectionLine:
    Key : TypeAlias = int

    def __init__(self, scene: int, batch: int, number: int, selected : bool) -> None:
        self.scene = scene
        self.batch = batch
        self.number = number
        self.selected = selected

    @property
    def key(self):
        return (self.scene, self.batch, self.number)

    def __str__(self) -> str:
        str = f"scene {self.scene}:batch {self.batch}:line {self.number}"
        return f"{str} [*]" if self.selected else str

    def __repr__(self) -> str:
        return str(self)

#########################################################################

class ProjectSelection():
    def __init__(self) -> None:
        self.scenes  : dict[SelectionScene.Key, SelectionScene] = {}
        self.batches : dict[SelectionBatch.Key, SelectionBatch] = {}
        self.lines : dict[SelectionLine.Key, SelectionLine] = {}

    @property
    def scene_numbers(self) -> list[int]:
        return sorted([ number for number in self.scenes.keys() ])

    @property
    def selected_scenes(self) -> list[SelectionScene]:
        return [ scene for scene in self.scenes.values() if scene.selected]

    @property
    def batch_numbers(self) -> list[tuple[int,int]]:
        return sorted([ (batch.scene, batch.number) for batch in self.batches.values() ])

    @property
    def selected_batches(self) -> list[SelectionBatch]:
        return [ batch for batch in self.batches.values() if batch.selected]

    @property
    def line_numbers(self) -> list[SelectionLine.Key]:
        return sorted([ number for number in self.lines.keys() if number is not None ])

    @property
    def selected_lines(self) -> list[SelectionLine]:
        return [line for line in self.lines.values() if line.selected ]

    def Any(self) -> bool:
        return bool(self.scene_numbers or self.batch_numbers or self.lines)

    def AnyScenes(self) -> bool:
        return True if self.selected_scenes else False

    def OnlyScenes(self) -> bool:
        return bool(self.selected_scenes and not (self.selected_batches or self.selected_lines))

    def AnyBatches(self) -> bool:
        return True if self.selected_batches else False

    def OnlyBatches(self) -> bool:
        return bool(self.selected_batches  and not (self.selected_scenes or self.selected_lines))

    def AnyLines(self) -> bool:
        return bool(self.selected_lines)

    def AllLinesInSameBatch(self) -> bool:
        """
        Are all selected lines part of the same batch?
        """
        lines = self.selected_lines
        return all(line.batch == lines[0].batch for line in lines)

    def MultipleSelected(self, max = None) -> bool:
        """
        Is more than one scene, batch or line selected?
        """
        if max:
            if len(self.selected_scenes) > max or len(self.selected_batches) > max or len(self.selected_lines) > max:
                return False

        return len(self.selected_scenes) > 1 or len(self.selected_batches) > 1 or len(self.selected_lines) > 1

    def IsContiguous(self) -> bool:
        """
        Are all selected scenes, batches and lines contiguous?
        """
        scene_numbers = sorted(scene.number for scene in self.selected_scenes)
        if scene_numbers and scene_numbers != list(range(scene_numbers[0], scene_numbers[0] + len(scene_numbers))):
            return False

        if not all(batch.scene == self.selected_batches[0].scene for batch in self.selected_batches):
            return False

        batch_numbers = sorted(batch.number for batch in self.selected_batches)
        if batch_numbers and batch_numbers != list(range(batch_numbers[0], batch_numbers[0] + len(batch_numbers))):
            return False

        if not all(batch.scene == self.selected_batches[0].scene for batch in self.selected_batches):
            return False

        line_numbers = sorted(line.number for line in self.selected_lines if line.number)
        if line_numbers and line_numbers != list(range(line_numbers[0], line_numbers[0] + len(line_numbers))):
            return False

        return True

    def AllTranslated(self) -> bool:
        """
        Are all selected batches translated?
        """
        return all(batch.translated for batch in self.selected_batches)

    def IsFirstInBatchSelected(self) -> bool:
        """
        Check whether the first line of any batch is selected
        """
        for scene, batch in self.batch_numbers:
            first_line = next((line for line in self.lines.values() if line.scene == scene and line.batch == batch), None)
            if first_line and first_line.selected:
                return True

        return False

    def IsFirstOrLastInBatchSelected(self) -> bool:
        """
        Check whether the first or last line of any batch is selected
        """
        line_dict = {}
        for line in list(self.lines.values()):
            key = (line.scene, line.batch, line.number)
            if key in line_dict:
                line_dict[key].selected = line_dict[key].selected or line.selected
            else:
                line_dict[key] = line

        for batch_lines in groupby(sorted(line_dict.values(), key=lambda x: (x.scene, x.batch, x.number)), key=lambda x: (x.scene, x.batch)):
            batch_lines = list(batch_lines[1])
            if batch_lines[0].selected or batch_lines[-1].selected:
                return True

        return False

    def IsFirstInSceneSelected(self) -> bool:
        """
        Check whether the first or last batch of any scene is selected
        """
        return bool(next((batch.number for batch in self.selected_batches if batch.number == 1), False))

    def IsFirstOrLastInSceneSelected(self) -> bool:
        """
        Check whether the first or last batch of any scene is selected
        """
        scene_batches = {}
        for scene in self.scenes:
            scene_batches[scene] = [batch for batch in self.batches if batch[0] == scene]

        for batch in self.selected_batches:
            if batch.number == 1 or batch.number == scene_batches[batch][-1][1]:
                return True

        return False

    def GetHierarchy(self) -> dict:
        """
        Hierarchical representation of selected lines/batches/scenes
        """
        scenes = {}

        for scene in self.selected_scenes:
            scenes[scene.number] = {}
        for batch in self.selected_batches:
            scene = scenes[batch.scene] = scenes.get(batch.scene) or {}
            scene[batch.number] = { 'lines': {} }

        for line in self.selected_lines:
            scene = scenes[line.scene] = scenes.get(line.scene) or {}
            batch = scene[line.batch] = scene.get(line.batch) or { 'lines': {} }
            batch['lines'][line.number] = line

        return scenes

    def AppendItem(self, model, index, selected : bool = True):
        """
        Accumulated selected batches, scenes and lines
        """
        item = model.data(index, role=Qt.ItemDataRole.UserRole)

        if isinstance(item, SceneItem):
            if selected or not item.number in self.scenes.keys():
                self.scenes[item.number] = SelectionScene(item.number, selected)

                children = [ model.index(i, 0, index) for i in range(model.rowCount(index))]
                for child_index in children:
                    self.AppendItem(model, child_index, False)

        elif isinstance(item, BatchItem):
            key = (item.scene, item.number)
            if selected or not key in self.batches:
                batch = SelectionBatch((item.scene, item.number), selected=selected, translated=item.translated)
                self.batches[key] = batch
                if not self.scenes.get(item.scene):
                    self.AppendItem(model, model.parent(index), False)

                for line in item.lines:
                    self.lines[line] = SelectionLine(batch.scene, batch.number, line, False)

    def AddSelectedLines(self, selected_lines : list[SelectionLine]):
        """
        Add selected lines to the selection
        """
        for line in selected_lines:
            self.lines[line.number] = line
            key = (line.scene, line.batch)
            if key not in self.batches:
                self.batches[key] = SelectionBatch(key, False)
                self.scenes[line.scene] = SelectionScene(line.scene, False)

    def __str__(self):
        if self.selected_lines:
            return f"{self.str_lines} in {self.str_batches}"
        if self.selected_scenes:
            return f"{self.str_scenes} with {self.str_lines} in {self.str_batches}"
        elif self.selected_batches:
            return f"{self.str_batches} with {self.str_lines}"
        elif self.lines:
            return f"{self.str_scenes} with {self.str_lines} in {self.str_batches}"
        elif self.scene_numbers:
            return f"{self.str_scenes}"
        else:
            return "Nothing selected"

    def __repr__(self):
        return str(self)

    @property
    def str_scenes(self):
        if self.selected_scenes:
            return self._count(len(self.scene_numbers), "scene", "scenes")
        else:
            return self._count(len(self.selected_scenes), "scene", "scenes")

    @property
    def str_batches(self):
        if self.selected_batches:
           return self._count(len(self.selected_batches), "batch", "batches")
        else:
            return self._count(len(self.batch_numbers), "batch", "batches")

    @property
    def str_linecount(self):
        return self._count(len(self.lines), "line", "lines")

    @property
    def str_selected_lines(self):
        return self._count(len(self.selected_lines), "line", "lines")

    @property
    def str_lines(self):
        if self.selected_lines:
            return f"{len(self.selected_lines)} lines selected"
        elif self.selected_batches:
            selected_batch_numbers = [ batch.number for batch in self.selected_batches ]
            batch_lines = [ x for x in self.lines.values() if x.batch in selected_batch_numbers ]
            if batch_lines:
                return f"{len(batch_lines)} lines"
        elif self.lines:
            return f"{len(self.lines)} lines"
        else:
            return "nothing selected"

    def _count(self, num, singular, plural):
        if num == 0:
            return f"no {plural}"
        elif num == 1:
            return f"1 {singular}"
        else:
            return f"{num} {plural}"

