from __future__ import annotations

import logging
import bisect
from typing import Any

from PySubtrans.Helpers.Localization import _
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.SubtitleLine import SubtitleLine
from PySubtrans.SubtitleScene import SubtitleScene
from PySubtrans.SubtitleBatch import SubtitleBatch
from PySubtrans.Subtitles import Subtitles
from PySubtrans.SubtitleProcessor import SubtitleProcessor
from PySubtrans.SubtitleBatcher import SubtitleBatcher


class SubtitleEditor:
    """
    Handles mutation operations on subtitle data with proper thread safety.
    Use as a context manager to ensure proper locking.
    """

    def __init__(self, subtitles: Subtitles) -> None:
        self.subtitles = subtitles
        self._lock_acquired = False

    def __enter__(self) -> SubtitleEditor:
        self.subtitles.lock.acquire()
        self._lock_acquired = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._lock_acquired:
            self.subtitles.lock.release()
            self._lock_acquired = False

    def PreProcess(self, preprocessor: SubtitleProcessor) -> None:
        """
        Preprocess subtitles
        """
        if self.subtitles.originals:
            self.subtitles.originals = preprocessor.PreprocessSubtitles(self.subtitles.originals)

    def AutoBatch(self, batcher: SubtitleBatcher) -> None:
        """
        Divide subtitles into scenes and batches based on threshold options
        """
        if self.subtitles.originals:
            self.subtitles.scenes = batcher.BatchSubtitles(self.subtitles.originals)

    def AddScene(self, scene: SubtitleScene) -> None:
        self.subtitles.scenes.append(scene)
        logging.debug("Added a new scene")

    def UpdateScene(self, scene_number: int, update: dict[str, Any]) -> Any:
        scene: SubtitleScene = self.subtitles.GetScene(scene_number)
        if not scene:
            raise ValueError(f"Scene {scene_number} does not exist")

        return scene.UpdateContext(update)

    def UpdateBatch(self, scene_number: int, batch_number: int, update: dict[str, Any]) -> bool:
        batch: SubtitleBatch = self.subtitles.GetBatch(scene_number, batch_number)
        if not batch:
            raise ValueError(f"Batch ({scene_number},{batch_number}) does not exist")

        return batch.UpdateContext(update)

    def UpdateLineText(self, line_number: int, original_text: str, translated_text: str) -> None:
        if self.subtitles.originals is None:
            raise SubtitleError("Original subtitles are missing!")

        original_line = next((original for original in self.subtitles.originals if original.number == line_number), None)
        if not original_line:
            raise ValueError(f"Line {line_number} not found")

        if original_text:
            original_line.text = original_text
            original_line.translation = translated_text

        if not translated_text:
            return

        translated_line = next((translated for translated in self.subtitles.translated if translated.number == line_number), None) if self.subtitles.translated else None
        if translated_line:
            translated_line.text = translated_text
            return

        translated_line = SubtitleLine.Construct(line_number, original_line.start, original_line.end, translated_text, original_line.metadata)

        if not self.subtitles.translated:
            self.subtitles.translated = []

        insertIndex = bisect.bisect_left([line.number for line in self.subtitles.translated], line_number)
        self.subtitles.translated.insert(insertIndex, translated_line)

    def DeleteLines(self, line_numbers: list[int]) -> list[tuple[int, int, list[SubtitleLine], list[SubtitleLine]]]:
        """
        Delete lines from the subtitles
        """
        deletions = []
        batches = self.subtitles.GetBatchesContainingLines(line_numbers)

        for batch in batches:
            deleted_originals, deleted_translated = batch.DeleteLines(line_numbers)
            if len(deleted_originals) > 0 or len(deleted_translated) > 0:
                deletion = (batch.scene, batch.number, deleted_originals, deleted_translated)
                deletions.append(deletion)

        if not deletions:
            raise ValueError("No lines were deleted from any batches")

        return deletions

    def MergeScenes(self, scene_numbers: list[int]) -> SubtitleScene:
        """
        Merge several (sequential) scenes into one scene
        """
        if not scene_numbers:
            raise ValueError("No scene numbers supplied to MergeScenes")

        scene_numbers = sorted(scene_numbers)
        if scene_numbers != list(range(scene_numbers[0], scene_numbers[0] + len(scene_numbers))):
            raise ValueError("Scene numbers to be merged are not sequential")

        scenes: list[SubtitleScene] = [scene for scene in self.subtitles.scenes if scene.number in scene_numbers]
        if len(scenes) != len(scene_numbers):
            raise ValueError(f"Could not find scenes {','.join([str(i) for i in scene_numbers])}")

        # Merge all scenes into the first
        merged_scene = scenes[0]
        merged_scene.MergeScenes(scenes[1:])

        # Slice out the merged scenes
        start_index = self.subtitles.scenes.index(scenes[0])
        end_index = self.subtitles.scenes.index(scenes[-1])
        self.subtitles.scenes = self.subtitles.scenes[:start_index + 1] + self.subtitles.scenes[end_index+1:]

        self.RenumberScenes()

        return merged_scene

    def MergeBatches(self, scene_number: int, batch_numbers: list[int]) -> None:
        """
        Merge several (sequential) batches from a scene into one batch
        """
        if not batch_numbers:
            raise ValueError("No batch numbers supplied to MergeBatches")

        scene: SubtitleScene|None = next((scene for scene in self.subtitles.scenes if scene.number == scene_number), None)
        if not scene:
            raise ValueError(f"Scene {str(scene_number)} not found")

        scene.MergeBatches(batch_numbers)

    def MergeLinesInBatch(self, scene_number: int, batch_number: int, line_numbers: list[int]) -> tuple[SubtitleLine, SubtitleLine|None]:
        """
        Merge several sequential lines together, remapping originals and translated lines if necessary.
        """
        batch: SubtitleBatch = self.subtitles.GetBatch(scene_number, batch_number)
        return batch.MergeLines(line_numbers)

    def SplitScene(self, scene_number: int, batch_number: int) -> None:
        """
        Split a scene into two at the specified batch number
        """
        scene: SubtitleScene = self.subtitles.GetScene(scene_number)
        batch: SubtitleBatch|None = scene.GetBatch(batch_number) if scene else None

        if not batch:
            raise ValueError(f"Scene {scene_number} batch {batch_number} does not exist")

        batch_index: int = scene.batches.index(batch)

        new_scene = SubtitleScene({ 'number': scene_number + 1})
        new_scene.batches = scene.batches[batch_index:]
        scene.batches = scene.batches[:batch_index]

        for number, batch in enumerate(new_scene.batches, start=1):
            batch.scene = new_scene.number
            batch.number = number

        split_index = self.subtitles.scenes.index(scene) + 1
        if split_index < len(self.subtitles.scenes):
            self.subtitles.scenes = self.subtitles.scenes[:split_index] + [new_scene] + self.subtitles.scenes[split_index:]
        else:
            self.subtitles.scenes.append(new_scene)

        self.RenumberScenes()

    def Sanitise(self) -> None:
        """
        Remove invalid lines, empty batches and empty scenes
        """
        for scene in self.subtitles.scenes:
            scene.batches = [batch for batch in scene.batches if batch.originals]

            for batch in scene.batches:
                batch.originals = [line for line in batch.originals if line.number and line.start is not None]
                if batch.translated:
                    batch.translated = [line for line in batch.translated if line.number and line.start is not None ]

                original_line_numbers = [line.number for line in batch.originals]
                unmatched_translated = [line for line in batch.translated if line.number not in original_line_numbers]
                if unmatched_translated:
                    logging.warning(_("Removing {} translations lines in batch ({},{}) that don't match an original line").format(len(unmatched_translated), batch.scene, batch.number))
                    batch.translated = [line for line in batch.translated if line not in unmatched_translated]

        self.subtitles.scenes = [scene for scene in self.subtitles.scenes if scene.batches]
        self.RenumberScenes()

    def RenumberScenes(self) -> None:
        """
        Ensure scenes are numbered sequentially
        """
        for scene_number, scene in enumerate(self.subtitles.scenes, start=1):
            scene.number = scene_number
            for batch_number, batch in enumerate(scene.batches, start=1):
                batch.scene = scene.number
                batch.number = batch_number

    def DuplicateOriginalsAsTranslations(self) -> None:
        """
        Duplicate original lines as translated lines if no translations exist (for testing)
        """
        for scene in self.subtitles.scenes:
            for batch in scene.batches:
                if batch.any_translated:
                    raise SubtitleError("Translations already exist")

                batch.translated = [ SubtitleLine.Construct(line.number, line.start, line.end, line.text or "", line.metadata) for line in batch.originals ]
