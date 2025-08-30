from __future__ import annotations

from copy import deepcopy
import os
import logging
import threading
from typing import Any
import bisect
from PySubtitle.Helpers.Text import IsRightToLeftText
from PySubtitle.Helpers.Localization import _
from PySubtitle.Instructions import DEFAULT_TASK_TYPE
from PySubtitle.Options import Options, SettingsType

from PySubtitle.SettingsType import SettingsType
from PySubtitle.Substitutions import Substitutions
from PySubtitle.SubtitleBatch import SubtitleBatch
from PySubtitle.SubtitleError import SubtitleError, SubtitleParseError
from PySubtitle.Helpers import GetInputPath, GetOutputPath
from PySubtitle.Helpers.Parse import ParseNames
from PySubtitle.SubtitleFileHandler import SubtitleFileHandler
from PySubtitle.SubtitleProcessor import SubtitleProcessor
from PySubtitle.SubtitleScene import SubtitleScene, UnbatchScenes
from PySubtitle.SubtitleLine import SubtitleLine
from PySubtitle.SubtitleData import SubtitleData
from PySubtitle.SubtitleBatcher import SubtitleBatcher

default_encoding = os.getenv('DEFAULT_ENCODING', 'utf-8')
fallback_encoding = os.getenv('DEFAULT_ENCODING', 'iso-8859-1')

class Subtitles:
    """
    High level class for manipulating subtitles
    """
    DEFAULT_PROJECT_SETTINGS : SettingsType = SettingsType({
        'provider': None,
        'model': None,
        'target_language': None,
        'prompt': None,
        'task_type': None,
        'instructions': None,
        'retry_instructions': None,
        'movie_name': None,
        'description': None,
        'names': None,
        'substitutions': None,
        'substitution_mode': None,
        'include_original': None,
        'add_right_to_left_markers': None,
        'instruction_file': None
    })

    def __init__(self, file_handler: SubtitleFileHandler, filepath: str | None = None, outputpath: str | None = None,
    ) -> None:
        self.originals: list[SubtitleLine] | None = None
        self.translated: list[SubtitleLine] | None = None
        self.start_line_number: int = 1
        self._scenes: list[SubtitleScene] = []
        self.lock = threading.RLock()

        self.sourcepath: str | None = GetInputPath(filepath)
        self.outputpath: str | None = outputpath or None

        self.file_handler: SubtitleFileHandler = file_handler
        self.metadata: dict[str, Any] = {}

        self.settings: SettingsType = deepcopy(self.DEFAULT_PROJECT_SETTINGS)

    @property
    def movie_name(self) -> str|None:
        return self._get_setting_str('movie_name')

    @property
    def target_language(self) -> str|None:
        return self._get_setting_str('target_language')
    
    @property
    def task_type(self) -> str:
        return self._get_setting_str('task_type') or DEFAULT_TASK_TYPE

    @property
    def has_subtitles(self) -> bool:
        return self.linecount > 0 or self.scenecount > 0

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
            raise SubtitleError("Subtitles have not been batched")

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
            raise SubtitleError("No line numbers supplied")

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

    def GetBatchContext(self, scene_number: int, batch_number: int, max_lines: int|None = None) -> dict[str, Any]:
        """
        Get context for a batch of subtitles, by extracting summaries from previous scenes and batches
        """
        with self.lock:
            scene = self.GetScene(scene_number)
            if not scene:
                raise SubtitleError(f"Failed to find scene {scene_number}")

            batch = self.GetBatch(scene_number, batch_number)
            if not batch:
                raise SubtitleError(f"Failed to find batch {batch_number} in scene {scene_number}")

            context : dict[str,Any] = {
                'scene_number': scene.number,
                'batch_number': batch.number,
                'scene': f"Scene {scene.number}: {scene.summary}" if scene.summary else f"Scene {scene.number}",
                'batch': f"Batch {batch.number}: {batch.summary}" if batch.summary else f"Batch {batch.number}"
            }

            if 'movie_name' in self.settings:
                context['movie_name'] = self._get_setting_str('movie_name')

            if 'description' in self.settings:
                context['description'] = self._get_setting_str('description')

            if 'names' in self.settings:
                context['names'] = ParseNames(self.settings.get('names', []))

            history_lines = self._get_history(scene_number, batch_number, max_lines)

            if history_lines:
                context['history'] = history_lines

        return context

    def LoadSubtitles(self, filepath: str|None = None) -> None:
        """
        Load subtitles from a file
        """
        if filepath:
            self.sourcepath = GetInputPath(filepath)
            # Set default output path using same format as input
            self.outputpath = GetOutputPath(self.sourcepath, self.target_language)

        if not self.sourcepath:
            raise ValueError("No source path set for subtitles")

        if not self.file_handler or not isinstance(self.file_handler, SubtitleFileHandler):
            raise SubtitleError(_("File type handler is unknown for {filepath}").format(filepath=self.sourcepath))
        
        try:
            with open(self.sourcepath, 'r', encoding=default_encoding, newline='') as f:
                data = self.file_handler.parse_file(f)

        except SubtitleParseError as e:
            logging.warning(_("Error parsing file... trying with fallback encoding: {}").format(str(e)))
            try:
                with open(self.sourcepath, 'r', encoding=fallback_encoding) as f:
                    data = self.file_handler.parse_file(f)
            except SubtitleParseError as e2:
                logging.error(_("Failed to parse file with fallback encoding: {}").format(str(e2)))
                raise e2

        with self.lock:
            self._renumber_if_needed(data.lines)
            self.originals = data.lines
            self.metadata = data.metadata

    def LoadSubtitlesFromString(self, subtitles_string: str) -> None:
        """
        Load subtitles from a string
        """
        try:
            with self.lock:
                data = self.file_handler.parse_string(subtitles_string)
                self._renumber_if_needed(data.lines)
                self.originals = data.lines
                self.metadata = data.metadata

        except SubtitleParseError as e:
            logging.error(_("Failed to parse subtitles string: {}").format(str(e)))

    def SaveOriginal(self, path: str|None = None) -> None:
        """
        Write original subtitles to a file
        """
        path = path or self.sourcepath
        if not path:
            raise ValueError("No file path set")

        with self.lock:
            originals = self.originals
            if originals:
                data = SubtitleData(lines=originals, metadata=self.metadata, start_line_number=self.start_line_number)
                subtitle_file = self.file_handler.compose(data)
                with open(path, 'w', encoding=default_encoding) as f:
                    f.write(subtitle_file)
            else:
                logging.warning(_("No original subtitles to save to {}").format(str(path)))

    def SaveTranslation(self, outputpath: str|None = None) -> None:
        """
        Write translated subtitles to a file
        """
        outputpath = outputpath or self.outputpath
        if not outputpath:
            if self.sourcepath and os.path.exists(self.sourcepath):
                outputpath = GetOutputPath(self.sourcepath, self.target_language)
            if not outputpath:
                raise Exception("I don't know where to save the translated subtitles")

        outputpath = os.path.normpath(outputpath)

        with self.lock:
            if not self.scenes:
                raise ValueError("No scenes in subtitles")

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

            data.metadata['Title'] = self.movie_name
            data.metadata['Language'] = self.target_language
            
            # Apply RTL markers if requested (handler will decide format-specific implementation)
            data.metadata['add_rtl_markers'] = self.settings.get('add_right_to_left_markers', False)
            
            subtitle_file = self.file_handler.compose(data)
            with open(outputpath, 'w', encoding=default_encoding) as f:
                f.write(subtitle_file)

            # Log a warning if any lines had no text or start time
            num_invalid = len([line for line in translated if line.start is None])
            if num_invalid:
                logging.warning(_("{} lines were invalid and were not written to the output file").format(num_invalid))

            num_empty = len([line for line in translated if not line.text])
            if num_empty:
                logging.warning(_("{} lines were empty and were not written to the output file").format(num_empty))

            self.translated = translated
            self.outputpath = outputpath

    def UpdateProjectSettings(self, settings: SettingsType) -> None:
        """
        Update the project settings
        """
        if isinstance(settings, Options):
            return self.UpdateProjectSettings(settings)

        with self.lock:
            self.settings.update({key: settings[key] for key in settings if key in self.DEFAULT_PROJECT_SETTINGS})

            names_list = self.settings.get('names', [])
            self.settings['names'] = ParseNames(names_list)
            substitions_list = self.settings.get('substitutions', [])
            if substitions_list:
                self.settings['substitutions'] = Substitutions.Parse(substitions_list)

            self._update_compatibility(self.settings)

    def UpdateOutputPath(self, outputpath: str|None = None) -> None:
        """
        Set or generate the output path for the translated subtitles
        """
        if not outputpath:
            outputpath = GetOutputPath(self.sourcepath, self.target_language)
        self.outputpath = outputpath

    def PreProcess(self, preprocessor: SubtitleProcessor) -> None:
        """
        Preprocess subtitles
        """
        with self.lock:
            if self.originals:
                self.originals = preprocessor.PreprocessSubtitles(self.originals)

    def AutoBatch(self, batcher: SubtitleBatcher) -> None:
        """
        Divide subtitles into scenes and batches based on threshold options
        """
        with self.lock:
            if self.originals:
                self.scenes = batcher.BatchSubtitles(self.originals)

    def AddScene(self, scene: SubtitleScene) -> None:
        with self.lock:
            self.scenes.append(scene)
            logging.debug("Added a new scene")

    def UpdateScene(self, scene_number: int, update: dict[str, Any]) -> Any:
        with self.lock:
            scene: SubtitleScene = self.GetScene(scene_number)
            if not scene:
                raise ValueError(f"Scene {scene_number} does not exist")

            return scene.UpdateContext(update)

    def UpdateBatch(self, scene_number: int, batch_number: int, update: dict[str, Any]) -> bool:
        with self.lock:
            batch: SubtitleBatch = self.GetBatch(scene_number, batch_number)
            if not batch:
                raise ValueError(f"Batch ({scene_number},{batch_number}) does not exist")

            return batch.UpdateContext(update)

    def UpdateLineText(self, line_number : int, original_text : str, translated_text : str) -> None:
        with self.lock:
            if self.originals is None:
                raise SubtitleError("Original subtitles are missing!")

            original_line = next((original for original in self.originals if original.number == line_number), None)
            if not original_line:
                raise ValueError(f"Line {line_number} not found")

            if original_text:
                original_line.text = original_text
                original_line.translation = translated_text

            if not translated_text:
                return

            translated_line = next((translated for translated in self.translated if translated.number == line_number), None) if self.translated else None
            if translated_line:
                translated_line.text = translated_text
                return

            translated_line = SubtitleLine.Construct(line_number, original_line.start, original_line.end, translated_text, original_line.metadata)

            if not self.translated:
                self.translated = []

            insertIndex = bisect.bisect_left([line.number for line in self.translated], line_number)
            self.translated.insert(insertIndex, translated_line)

    def DeleteLines(self, line_numbers: list[int]) -> list[tuple[int, int, list[SubtitleLine], list[SubtitleLine]]]:
        """
        Delete lines from the subtitles
        """
        deletions = []
        with self.lock:
            batches = self.GetBatchesContainingLines(line_numbers)

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

        with self.lock:
            scenes : list[SubtitleScene] = [scene for scene in self.scenes if scene.number in scene_numbers]
            if len(scenes) != len(scene_numbers):
                raise ValueError(f"Could not find scenes {','.join([str(i) for i in scene_numbers])}")

            # Merge all scenes into the first
            merged_scene = scenes[0]
            merged_scene.MergeScenes(scenes[1:])

            # Slice out the merged scenes
            start_index = self.scenes.index(scenes[0])
            end_index = self.scenes.index(scenes[-1])
            self.scenes = self.scenes[:start_index + 1] + self.scenes[end_index+1:]

            self._renumber_scenes()

        return merged_scene

    def MergeBatches(self, scene_number: int, batch_numbers: list[int]) -> None:
        """
        Merge several (sequential) batches from a scene into one batch
        """
        if not batch_numbers:
            raise ValueError("No batch numbers supplied to MergeBatches")

        with self.lock:
            scene : SubtitleScene|None = next((scene for scene in self.scenes if scene.number == scene_number), None)
            if not scene:
                raise ValueError(f"Scene {str(scene_number)} not found")

            scene.MergeBatches(batch_numbers)

    def MergeLinesInBatch(self, scene_number: int, batch_number: int, line_numbers: list[int]) -> tuple[SubtitleLine, SubtitleLine|None]:
        """
        Merge several sequential lines together, remapping originals and translated lines if necessary.
        """
        with self.lock:
            batch : SubtitleBatch = self.GetBatch(scene_number, batch_number)
            return batch.MergeLines(line_numbers)

    def SplitScene(self, scene_number: int, batch_number: int) -> None:
        """
        Split a scene into two at the specified batch number
        """
        with self.lock:
            scene : SubtitleScene = self.GetScene(scene_number)
            batch : SubtitleBatch|None = scene.GetBatch(batch_number) if scene else None

            if not batch:
                raise ValueError(f"Scene {scene_number} batch {batch_number} does not exist")

            batch_index : int = scene.batches.index(batch)

            new_scene = SubtitleScene({ 'number' : scene_number + 1})
            new_scene.batches = scene.batches[batch_index:]
            scene.batches = scene.batches[:batch_index]

            for number, batch in enumerate(new_scene.batches, start=1):
                batch.scene = new_scene.number
                batch.number = number

            split_index = self.scenes.index(scene) + 1
            if split_index < len(self.scenes):
                self.scenes = self.scenes[:split_index] + [new_scene] + self.scenes[split_index:]
            else:
                self.scenes.append(new_scene)

            self._renumber_scenes()

    def Sanitise(self) -> None:
        """
        Remove invalid lines, empty batches and empty scenes
        """
        with self.lock:
            for scene in self.scenes:
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

        self.scenes = [scene for scene in self.scenes if scene.batches]
        self._renumber_scenes()

    def _renumber_scenes(self) -> None:
        """
        Ensure scenes are numbered sequentially
        """
        for scene_number, scene in enumerate(self.scenes, start = 1):
            scene.number = scene_number
            for batch_number, batch in enumerate(scene.batches, start = 1):
                batch.scene = scene.number
                batch.number = batch_number

    def _renumber_if_needed(self, lines : list[SubtitleLine]|None) -> None:
        """
        Renumber subtitle lines if any have number 0 (indicating missing/invalid indices)
        """
        if lines and any(line.number == 0 for line in lines):
            logging.warning(_("Renumbering subtitle lines due to missing indices"))
            for line_number, line in enumerate(lines, start=1):
                line.number = line_number

    def _get_history(self, scene_number: int, batch_number: int, max_lines: int|None = None) -> list[str]:
        """
        Get a list of historical summaries up to a given scene and batch number
        """
        history_lines : list[str] = []
        last_summary : str = ""

        scenes = [scene for scene in self.scenes if scene.number and scene.number < scene_number]
        for scene in [scene for scene in scenes if scene.summary]:
            if scene.summary != last_summary:
                history_lines.append(f"scene {scene.number}: {scene.summary}")
                last_summary = scene.summary or ""

        batches = [batch for batch in self.GetScene(scene_number).batches if batch.number is not None and batch.number < batch_number]
        for batch in [batch for batch in batches if batch.summary]:
            if batch.summary != last_summary:
                history_lines.append(f"scene {batch.scene} batch {batch.number}: {batch.summary}")
                last_summary = batch.summary or ""

        if max_lines:
            history_lines = history_lines[-max_lines:]

        return history_lines

    def _merge_original_and_translated(self, originals: list[SubtitleLine], translated: list[SubtitleLine]) -> list[SubtitleLine]:
        lines = {item.key: SubtitleLine(item) for item in originals if item.key}

        for item in translated:
            if item.key in lines:
                line = lines[item.key]
                line.text = f"{line.text}\n{item.text}"

        return sorted(lines.values(), key=lambda item: item.key)

    def _get_setting_str(self, key: str, default: str|None = None) -> str|None:
        """
        Get a setting as a string, or None if not set
        """
        value = self.settings.get(key, default)
        return value if isinstance(value, str) else default

    def _update_compatibility(self, settings: SettingsType) -> None:
        """
        Update settings for compatibility with older versions
        """
        if not settings.get('description') and settings.get('synopsis'):
            settings['description'] = settings.get('synopsis')

        if settings.get('characters'):
            names = settings.get_str_list('names')
            names.extend(settings.get_str_list('characters'))
            settings['names'] = names
            del settings['characters']

        if settings.get('gpt_prompt'):
            settings['prompt'] = settings['gpt_prompt']
            del settings['gpt_prompt']

        if settings.get('gpt_model'):
            settings['model'] = settings['gpt_model']
            del settings['gpt_model']

        if not settings.get('substitution_mode'):
            settings['substitution_mode'] = "Partial Words" if settings.get('match_partial_words') else "Auto"