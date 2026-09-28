from datetime import timedelta
from PySubtrans.Options import SettingsType
from PySubtrans.SubtitleBatch import SubtitleBatch
from PySubtrans.SubtitleScene import SubtitleScene
from PySubtrans.SubtitleLine import SubtitleLine

class SubtitleBatcher:
    def __init__(self, settings : SettingsType):
        """ Initialize a SubtitleBatcher helper class with settings """
        self.min_batch_size : int = settings.get_int('min_batch_size') or 1
        self.max_batch_size : int = settings.get_int('max_batch_size') or 100
        self.fix_overlaps : bool = settings.get_bool('prevent_overlapping_times', False)
        self.min_gap : timedelta = settings.get_timedelta('min_gap', timedelta(seconds=0.05))

        scene_threshold_seconds : float = settings.get_float('scene_threshold') or 30.0
        self.scene_threshold : timedelta = timedelta(seconds=scene_threshold_seconds)

    def BatchSubtitles(self, lines : list[SubtitleLine]) -> list[SubtitleScene]:
        if self.min_batch_size > self.max_batch_size:
            raise ValueError("min_batch_size must be less than max_batch_size.")

        scenes : list[SubtitleScene] = []
        current_lines : list[SubtitleLine] = []
        previous_line : SubtitleLine|None = None

        for line in lines:
            if line.start is None or line.end is None:
                raise ValueError(f"Line {line.number} has missing start or end time.")

            if self.fix_overlaps and previous_line and previous_line.end > line.start:
                # Preserve the next start time by trimming the previous end, without creating a non-positive duration.
                latest_end = line.start - self.min_gap
                if previous_line.end > latest_end and latest_end > previous_line.start:
                    previous_line.end = latest_end

            gap = line.start - previous_line.end if previous_line else None

            if gap is not None and gap > self.scene_threshold:
                if current_lines:
                    self.CreateNewScene(scenes, current_lines)
                    current_lines = []

            current_lines.append(line)
            previous_line = line

        # Handle any remaining lines
        if current_lines:
            self.CreateNewScene(scenes, current_lines)

        return scenes

    def CreateNewScene(self, scenes : list[SubtitleScene], current_lines : list[SubtitleLine]):
        """
        Create a scene and add lines to it in batches
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
