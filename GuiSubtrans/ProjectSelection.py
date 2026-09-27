from typing import TypeAlias
from PySide6.QtCore import Qt

from GuiSubtrans.ViewModel.BatchItem import BatchItem
from GuiSubtrans.ViewModel.LineItem import LineItem
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

    def __init__(self, scene: int, batch: int, number: int, selected : bool, translated : bool = False, first_in_batch : bool = False) -> None:
        self.scene = scene
        self.batch = batch
        self.number = number
        self.selected = selected
        self.translated = translated
        self.first_in_batch = first_in_batch

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
    """
    Scenes, batches and lines selected in the project view.

    Entries flagged as selected were chosen by the user.
    Unselected entries are the contents of a selected scene or batch, or the parents of a selected item.
    Structural details such as batch boundaries are captured when items are added.
    """
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

    @property
    def effective_lines(self) -> list[SelectionLine]:
        """
        Selected lines if there are any, otherwise all lines in the selected scenes and batches.
        """
        return self.selected_lines or list(self.lines.values())

    @property
    def effective_batch_numbers(self) -> list[SelectionBatch.Key]:
        """
        Selected batches plus all batches in selected scenes.
        """
        selected_scene_numbers = { scene.number for scene in self.selected_scenes }
        return sorted(
            batch.key for batch in self.batches.values()
            if batch.selected or batch.scene in selected_scene_numbers
        )

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
        return all((line.scene, line.batch) == (lines[0].scene, lines[0].batch) for line in lines)

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

    def AnyTranslated(self) -> bool:
        """
        Are any selected batches translated?
        """
        return any(batch.translated for batch in self.selected_batches)

    def AllTranslated(self) -> bool:
        """
        Are all selected batches translated?
        """
        return all(batch.translated for batch in self.selected_batches)

    def AnyLinesTranslated(self) -> bool:
        """
        Are any lines included in the selection translated?
        """
        return any(line.translated for line in self.effective_lines)

    def AllLinesTranslated(self) -> bool:
        """
        Are all lines included in the selection translated?
        """
        lines = self.effective_lines
        return bool(lines) and all(line.translated for line in lines)

    def IsFirstInBatchSelected(self) -> bool:
        """
        Check whether the first line of any batch is selected
        """
        return any(line.first_in_batch for line in self.selected_lines)

    def IsFirstInSceneSelected(self) -> bool:
        """
        Check whether the first batch of any scene is selected
        """
        return bool(next((batch.number for batch in self.selected_batches if batch.number == 1), False))

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

                # Register the parent scene only, not its other batches
                if item.scene not in self.scenes:
                    self.scenes[item.scene] = SelectionScene(item.scene, False)

                first_line_number = item.first_line_number
                for line_number, line_item in item.lines.items():
                    self.lines[line_number] = SelectionLine(
                        batch.scene,
                        batch.number,
                        line_number,
                        False,
                        translated=line_item.translation is not None,
                        first_in_batch=line_number == first_line_number,
                    )

    def AddLineItems(self, line_items : list[LineItem]):
        """
        Add line items selected in the subtitle view
        """
        selected_lines = []
        for line_item in line_items:
            batch_item = line_item.parent()
            if not isinstance(batch_item, BatchItem):
                continue

            selected_lines.append(SelectionLine(
                batch_item.scene,
                batch_item.number,
                line_item.number,
                True,
                translated=line_item.translation is not None,
                first_in_batch=line_item.number == batch_item.first_line_number,
            ))

        self.AddSelectedLines(selected_lines)

    def AddSelectedLines(self, selected_lines : list[SelectionLine]):
        """
        Add selected lines to the selection
        """
        for line in selected_lines:
            self.lines[line.number] = line
            key = (line.scene, line.batch)
            if key not in self.batches:
                self.batches[key] = SelectionBatch(key, False)

            if line.scene not in self.scenes:
                self.scenes[line.scene] = SelectionScene(line.scene, False)

    def __str__(self):
        if self.selected_lines:
            return f"{self.str_lines} selected in {self.str_batches}"
        elif self.selected_scenes and self.selected_batches:
            selected_batches = self._count(len(self.selected_batches), "batch", "batches")
            return f"{self.str_scenes} and {selected_batches} with {self.str_lines}"
        elif self.selected_scenes:
            return f"{self.str_scenes} with {self.str_lines} in {self.str_batches}"
        elif self.selected_batches:
            return f"{self.str_batches} with {self.str_lines}"
        else:
            return "Nothing selected"

    def __repr__(self):
        return str(self)

    @property
    def str_scenes(self):
        return self._count(len(self.selected_scenes), "scene", "scenes")

    @property
    def str_batches(self):
        if self.selected_lines:
            batch_keys = { (line.scene, line.batch) for line in self.selected_lines }
            return self._count(len(batch_keys), "batch", "batches")
        else:
            return self._count(len(self.effective_batch_numbers), "batch", "batches")

    @property
    def str_lines(self):
        return self._count(len(self.effective_lines), "line", "lines")

    def _count(self, num, singular, plural):
        if num == 0:
            return f"no {plural}"
        elif num == 1:
            return f"1 {singular}"
        else:
            return f"{num} {plural}"
