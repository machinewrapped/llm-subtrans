from __future__ import annotations

from copy import deepcopy
import os
import logging
import threading
from typing import Any
from PySubtrans.Helpers.Localization import _
from PySubtrans.Options import Options

from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleBatch import SubtitleBatch
from PySubtrans.SubtitleError import SubtitleError, SubtitleParseError
from PySubtrans.Helpers import GetInputPath, GetOutputPath
from PySubtrans.SubtitleFileHandler import SubtitleFileHandler, default_encoding
from PySubtrans.SubtitleFormatRegistry import SubtitleFormatRegistry
from PySubtrans.SubtitleScene import SubtitleScene, UnbatchScenes
from PySubtrans.SubtitleLine import SubtitleLine
from PySubtrans.SubtitleData import SubtitleData

class Subtitles:
    """
    High level class for manipulating subtitles
    """

    def __init__(self, filepath: str|None = None, outputpath: str|None = None, settings: SettingsType|None = None) -> None:
        self.originals : list[SubtitleLine]|None = None
        self.translated : list[SubtitleLine]|None = None
        self.start_line_number : int = 1
        self._scenes : list[SubtitleScene] = []
        self.lock = threading.RLock()

        self.sourcepath : str|None = GetInputPath(filepath)
        self.outputpath : str|None = outputpath or None

        self.metadata : dict[str, Any] = {}
        self.file_format : str|None = None

        self.settings : SettingsType = SettingsType(deepcopy(settings)) if settings else SettingsType()

    @property
    def has_subtitles(self) -> bool:
        return self.linecount > 0 or self.scenecount > 0

    @property
    def any_translated(self) -> bool:
        with self.lock:
            return any(scene.any_translated for scene in self.scenes) if self.scenes else False

    @property
    def all_translated(self) -> bool:
        with self.lock:
            return all(scene.all_translated for scene in self.scenes) if self.scenes else False

    @property
    def linecount(self) -> int:
        with self.lock:
            return len(self.originals) if self.originals else 0

    @property
    def scenecount(self) -> int:
        with self.lock:
            return len(self.scenes) if self.scenes else 0

    @property
    def scenes(self) -> list[SubtitleScene]:
        return self._scenes

    @scenes.setter
    def scenes(self, scenes: list[SubtitleScene]):
        with self.lock:
            self._scenes = scenes
            self.originals, self.translated, dummy = UnbatchScenes(scenes) # type: ignore[unused-ignore]
            self.start_line_number = (self.originals[0].number if self.originals else 1) or 1

    def GetScene(self, scene_number : int) -> SubtitleScene:
        """
        Get a scene by number
        """
        if not self.scenes:
            raise SubtitleError(_("Subtitles have not been batched"))

        with self.lock:
            matches = [ scene for scene in self.scenes if scene.number == scene_number ]

        if not matches:
            raise SubtitleError(f"Scene {scene_number} does not exist")

        if len(matches) > 1:
            raise SubtitleError(f"There is more than one scene {scene_number}!")

        return matches[0]

    def GetBatch(self, scene_number : int, batch_number : int) -> SubtitleBatch:
        """
        Get a batch by scene and batch number
        """
        with self.lock:
            scene = self.GetScene(scene_number)
            for batch in scene.batches:
                if batch.number == batch_number:
                    return batch

        raise SubtitleError(f"Scene {scene_number} batch {batch_number} doesn't exist")

    def GetOriginalLine(self, line_number : int) -> SubtitleLine|None:
        """
        Get a line by number
        """
        if self.originals:
            with self.lock:
                return next((line for line in self.originals if line.number == line_number), None)

    def GetTranslatedLine(self, line_number : int) -> SubtitleLine|None:
        """
        Get a translated line by number
        """
        if self.translated:
            with self.lock:
                return next((line for line in self.translated if line.number == line_number), None)

    def GetBatchContainingLine(self, line_number: int) -> SubtitleBatch|None:
        """
        Get the batch containing a line number
        """
        if not self.scenes:
            raise SubtitleError("Subtitles have not been batched yet")

        for scene in self.scenes:
            if scene.first_line_number is not None and scene.first_line_number > line_number:
                break

            if scene.last_line_number is None or scene.last_line_number >= line_number:
                for batch in scene.batches:
                    if batch.first_line_number is not None and batch.first_line_number > line_number:
                        break

                    if batch.last_line_number is None or batch.last_line_number >= line_number:
                        return batch

    def GetBatchesContainingLines(self, line_numbers : list[int]) -> list[SubtitleBatch]:
        """
        Find the set of unique batches containing the line numbers
        """
        if not line_numbers:
            raise ValueError("No line numbers supplied")

        if not self.scenes:
            raise SubtitleError("Subtitles have not been batched yet")

        sorted_line_numbers = sorted(line_numbers)

        next_line_index = 0
        line_number_count = len(sorted_line_numbers)
        out_batches : list[SubtitleBatch] = []

        for scene in self.scenes:
            next_line_number = sorted_line_numbers[next_line_index]
            if scene.last_line_number is None or scene.last_line_number < next_line_number:
                continue

            if scene.first_line_number is not None and scene.first_line_number > next_line_number:
                raise SubtitleError(f"Line {next_line_number} not found in any scene")

            for batch in scene.batches:
                if batch.last_line_number is None or batch.last_line_number < next_line_number:
                    continue

                if batch.first_line_number is not None and batch.first_line_number > next_line_number:
                    raise SubtitleError(f"Line {next_line_number} not found in any batch")

                out_batches.append(batch)

                last_line_in_batch = batch.last_line_number
                while next_line_index < line_number_count and last_line_in_batch >= sorted_line_numbers[next_line_index]:
                    next_line_index += 1

                if next_line_index >= line_number_count:
                    return out_batches

                next_line_number = sorted_line_numbers[next_line_index]

        return out_batches


    def LoadSubtitles(self, filepath: str|None = None) -> None:
        """
        Load subtitles from a file
        """
        if filepath:
            self.sourcepath = GetInputPath(filepath)

        if not self.sourcepath:
            raise ValueError("No source path set for subtitles")

        try:
            file_handler: SubtitleFileHandler = SubtitleFormatRegistry.create_handler(filename=self.sourcepath)

            data = file_handler.load_file(self.sourcepath)

        except SubtitleParseError as e:
            logging.debug(f"Error parsing file: {e}")
            logging.warning(_("Error parsing file... attempting format detection"))
            data = SubtitleFormatRegistry.detect_format_and_load_file(self.sourcepath)

        with self.lock:
            self._renumber_if_needed(data.lines)
            self.originals = data.lines
            self.metadata = data.metadata
            self.file_format = data.detected_format
            if self.outputpath is None:
                self.outputpath = GetOutputPath(self.sourcepath, "translated", self.file_format)

    def LoadSubtitlesFromString(self, subtitles_string: str, file_handler: SubtitleFileHandler) -> None:
        """
        Load subtitles from a string
        """
        try:
            with self.lock:
                data = file_handler.parse_string(subtitles_string)
                self._renumber_if_needed(data.lines)
                self.originals = data.lines
                self.metadata = data.metadata
                self.file_format = data.detected_format

        except SubtitleParseError as e:
            logging.error(_("Failed to parse subtitles string: {}").format(str(e)))

    def SaveOriginal(self, path: str|None = None) -> None:
        """
        Write original subtitles to a file (not a common operation)
        """
        path = path or self.sourcepath
        if not path:
            raise SubtitleError(_("No file path set"))

        with self.lock:
            originals = self.originals
            if originals:
                file_handler = SubtitleFormatRegistry.create_handler(filename=path)
                data = SubtitleData(lines=originals, metadata=self.metadata, start_line_number=self.start_line_number)
                subtitle_file = file_handler.compose(data)
                with open(path, 'w', encoding=default_encoding) as f:
                    f.write(subtitle_file)
            else:
                logging.warning(_("No original subtitles to save to {}").format(str(path)))

    def SaveTranslation(self, outputpath: str|None = None) -> None:
        """
        Write translated subtitles to a file
        """
        outputpath = outputpath or self.outputpath
        if not outputpath and self.sourcepath and os.path.exists(self.sourcepath):
            outputpath = GetOutputPath(self.sourcepath, "translated", self.file_format)
            logging.warning(_("No output path specified, saving to {}").format(str(outputpath)))
            
        if not outputpath:
            raise SubtitleError(_("I don't know where to save the translated subtitles"))

        outputpath = os.path.normpath(outputpath)

        file_handler = SubtitleFormatRegistry.create_handler(filename=outputpath)
            
        with self.lock:
            if not self.scenes:
                raise ValueError(_("No scenes in subtitles"))

            # Linearise the translation
            originals, translated, untranslated = UnbatchScenes(self.scenes) # type: ignore[unused-ignore]

            if not translated:
                logging.error(_("No subtitles translated"))
                return

            if self.settings.get('include_original'):
                translated = self._merge_original_and_translated(originals, translated)

            logging.info(_("Saving translation to {}").format(str(outputpath)))

            # Use file handler for format-agnostic saving with metadata preservation
            data = SubtitleData(
                lines=translated, 
                metadata=self.metadata, 
                start_line_number=self.start_line_number
            )

            data.metadata['Title'] = self.settings.get_str('movie_name', data.metadata.get('Title'))
            if self.settings.get_str('target_language'):
                data.metadata['Language'] = self.settings.get_str('target_language')
            
            # Apply RTL markers if requested (handler will decide format-specific implementation)
            data.metadata['add_rtl_markers'] = self.settings.get('add_right_to_left_markers', False)

            subtitle_file = file_handler.compose(data)
            with open(outputpath, 'w', encoding=default_encoding) as f:
                f.write(subtitle_file)

            self.translated = translated
            self.outputpath = outputpath

    def UpdateSettings(self, settings: SettingsType) -> None:
        """
        Update the subtitle settings
        """
        if isinstance(settings, Options):
            settings = SettingsType(settings)

        with self.lock:
            self.settings.update(settings)

    def _renumber_if_needed(self, lines : list[SubtitleLine]|None) -> None:
        """
        Renumber subtitle lines if any have number 0 (indicating missing/invalid indices)
        """
        if lines and any(line.number == 0 for line in lines):
            logging.warning(_("Renumbering subtitle lines due to missing indices"))
            for line_number, line in enumerate(lines, start=1):
                line.number = line_number


    def _merge_original_and_translated(self, originals: list[SubtitleLine], translated: list[SubtitleLine]) -> list[SubtitleLine]:
        lines = {item.key: SubtitleLine(item) for item in originals if item.key}

        for item in translated:
            if item.key in lines:
                line = lines[item.key]
                line.text = f"{line.text}\n{item.text}"

        return sorted(lines.values(), key=lambda item: item.key)

