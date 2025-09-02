from datetime import timedelta
from PySubtitle.Options import SettingsType
from PySubtitle.SubtitleBatch import SubtitleBatch
from PySubtitle.SubtitleScene import SubtitleScene
from PySubtitle.SubtitleLine import SubtitleLine

class SubtitleBatcher:
    def __init__(self, settings : SettingsType):
        """ Initialize a SubtitleBatcher helper class with settings """
        self.min_batch_size : int = settings.get_int('min_batch_size') or 1
        self.max_batch_size : int = settings.get_int('max_batch_size') or 100
        self.fix_overlaps : bool = settings.get_bool('prevent_overlapping_times', False)

        scene_threshold_seconds : float = settings.get_float('scene_threshold') or 30.0
        self.scene_threshold : timedelta = timedelta(seconds=scene_threshold_seconds)

    def BatchSubtitles(self, lines : list[SubtitleLine]) -> list[SubtitleScene]:
        if self.min_batch_size > self.max_batch_size:
            raise ValueError("min_batch_size must be less than max_batch_size.")

        scenes : list[SubtitleScene] = []
        current_lines : list[SubtitleLine] = []
        last_endtime : timedelta|None = None

        for line in lines:
            if line.start is None or line.end is None:
                raise ValueError(f"Line {line.number} has missing start or end time.")

            # Fix overlapping display times (otherwise gaps can be negative)
            if self.fix_overlaps and last_endtime and line.start < last_endtime:
                line.start = last_endtime + timedelta(milliseconds=10)

            gap = line.start - last_endtime if last_endtime is not None else None

            if gap is not None and gap > self.scene_threshold:
                if current_lines:
                    self.CreateNewScene(scenes, current_lines)
                    current_lines = []

            current_lines.append(line)
            last_endtime = line.end

        # Handle any remaining lines
        if current_lines:
            self.CreateNewScene(scenes, current_lines)

        return scenes

    def CreateNewScene(self, scenes : list[SubtitleScene], current_lines : list[SubtitleLine]):
        """
        Create a scene and lines to it in batches
        """
        scene = SubtitleScene()
        scenes.append(scene)
        scene.number = len(scenes)

        split_lines : list[list[SubtitleLine]] = self._split_lines(current_lines)

        for lines in split_lines:
            batch : SubtitleBatch = scene.AddNewBatch()
            batch._originals = lines

        return scene

    def _split_lines(self, lines : list[SubtitleLine]) -> list[list[SubtitleLine]]:
        """
        Recursively divide the lines at the largest gap until there is no batch larger than the maximum batch size
        """
        # If the batch is small enough, we're done
        num_lines = len(lines)
        if num_lines <= self.max_batch_size:
            return [ lines ]

        # Find the longest gap starting from the min_batch_size index
        longest_gap : timedelta = timedelta(seconds=0)
        split_index : int = self.min_batch_size
        last_split_index : int = num_lines - self.min_batch_size

        if last_split_index > split_index:
            for i in range(split_index, last_split_index):
                if lines[i].start is None:
                    raise ValueError(f"Line {lines[i].number} has no start time.")

                if lines[i - 1].end is None:
                    raise ValueError(f"Line {lines[i - 1].number} has no end time.")

                gap : timedelta = lines[i].start - lines[i - 1].end
                if gap > longest_gap:
                    longest_gap = gap
                    split_index = i

        # Split the batch into two
        left = lines[:split_index]
        right = lines[split_index:]

        # Recursively split the batches and concatenate the lists
        return self._split_lines(left) + self._split_lines(right)

