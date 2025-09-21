from collections import Counter
from collections.abc import Sequence
from datetime import timedelta
from typing import Any, TypeAlias

from PySubtrans.Options import SettingsType
from PySubtrans.Subtitles import Subtitles
from PySubtrans.SubtitleScene import SubtitleScene
from PySubtrans.SubtitleBatch import SubtitleBatch
from PySubtrans.SubtitleBatcher import SubtitleBatcher
from PySubtrans.SubtitleLine import SubtitleLine


LineData : TypeAlias = tuple[timedelta|str, timedelta|str, str] | tuple[timedelta|str, timedelta|str, str, dict[str, Any]]

class SubtitleBuilder:
    """
    A helper class for programmatically building subtitle structures with fine-grained control.

    Provides a fluent API for preparing subtitles for translation. 
    
    Scenes will be automatically divided into batches using gap lengths to determine split points.

    Usage:
    >>> builder = SubtitleBuilder(max_batch_size=100)
    >>> subtitles = (builder
    ...     .AddScene(summary="Opening dialogue")
    ...     .BuildLine(timedelta(seconds=1), timedelta(seconds=3), "Hello...")
    ...     .BuildLine(timedelta(seconds=4), timedelta(seconds=6), "Nice to meet you!")
    ...     .BuildLine(timedelta(seconds=8), timedelta(seconds=10), "We need to talk.")
    ...     .AddScene(summary="Action sequence")  # New scene
    ...     .BuildLine(timedelta(seconds=65), timedelta(seconds=67), "Look out!")
    ...     # ...
    ...     .Build()
    ... )
    """
    def __init__(self, max_batch_size : int = 100, min_batch_size : int = 1):
        """
        Initialize SubtitleBuilder.

        Parameters
        ----------
        max_batch_size : int
            Maximum number of lines per batch.
        min_batch_size : int
            Minimum size hint for batches. Helps avoid very small batches.
        """
        self._scenes : list[SubtitleScene] = []
        self._current_scene : SubtitleScene|None = None
        self._current_line_number : int = 0
        self._accumulated_lines : list[SubtitleLine] = []
        batch_settings : SettingsType = SettingsType({
            'max_batch_size': max_batch_size,
            'min_batch_size': min_batch_size,
        })
        self._batcher : SubtitleBatcher = SubtitleBatcher(batch_settings)

    def AddScene(self, summary : str|None = None) -> 'SubtitleBuilder':
        """
        Add a new scene. Lines added after this will be automatically organized into batches.

        Parameters
        ----------
        summary : str|None
            Optional summary of the scene content.
        context : dict[str, Any]|None
            Optional context metadata for the scene.

        Returns
        -------
        SubtitleBuilder
            Returns self for method chaining.
        """
        # Process any accumulated lines from previous scene
        self._finalize_current_scene()

        scene_number = len(self._scenes) + 1

        self._current_scene = SubtitleScene({'number': scene_number})
        if summary:
            self._current_scene.context['summary'] = summary

        self._scenes.append(self._current_scene)
        self._accumulated_lines = []

        return self

    def AddLine(self, line : SubtitleLine) -> 'SubtitleBuilder':
        """
        Add a SubtitleLine to the current scene.

        Parameters
        ----------
        line : SubtitleLine
            The subtitle line object to add.

        Returns
        -------
        SubtitleBuilder
            Returns self for method chaining.
        """
        if not self._current_scene:
            self.AddScene()

        self._accumulated_lines.append(line)

        return self

    def BuildLine(self, start : timedelta|str, end : timedelta|str, text : str, metadata : dict[str, Any]|None = None) -> 'SubtitleBuilder':
        """
        Build a SubtitleLine from parameters and add it to the current scene.

        Parameters
        ----------
        start : timedelta|str
            Start time as timedelta or SRT format string.
        end : timedelta|str
            End time as timedelta or SRT format string.
        text : str
            The subtitle text content.
        metadata : dict[str, Any]|None
            Optional metadata for the line.

        Returns
        -------
        SubtitleBuilder
            Returns self for method chaining.
        """
        self._current_line_number += 1
        line : SubtitleLine = SubtitleLine.Construct(self._current_line_number, start, end, text, metadata)

        return self.AddLine(line)

    def AddLines(self, lines : Sequence[SubtitleLine] | Sequence[LineData]) -> 'SubtitleBuilder':
        """
        Add multiple subtitle lines to the current scene. 

        Parameters
        ----------
        lines : Sequence[SubtitleLine] | Sequence[LineData]
            Either a sequence of SubtitleLine instances or tuples (start, end, text[, metadata]).

        Returns
        -------
        SubtitleBuilder
            Returns self for method chaining.
        """
        for line_data in lines:
            if isinstance(line_data, SubtitleLine):
                self.AddLine(line_data)

            elif isinstance(line_data, tuple):
                if len(line_data) == 3:
                    start, end, text = line_data
                    self.BuildLine(start, end, text)
                elif len(line_data) == 4:
                    start, end, text, metadata = line_data
                    self.BuildLine(start, end, text, metadata)
                else:
                    raise ValueError(f"Invalid line data tuple length: {line_data}")
            else:
                raise ValueError(f"Invalid line data format: {line_data}")

        return self

    def Build(self) -> Subtitles:
        """
        Finalize and return the built Subtitles instance.

        Returns
        -------
        Subtitles
            The completed subtitles organised into scenes and batches.
        """
        self._finalize_current_scene()

        subtitles = Subtitles()
        subtitles.scenes = self._scenes
        return subtitles

    def _finalize_current_scene(self) -> None:
        """
        Split accumulated lines into batches to stay within max_batch_size.
        """
        if not self._current_scene or not self._accumulated_lines:
            return

        line_numbers : list[int] = []
        for line in self._accumulated_lines:
            if line.number is None:
                raise ValueError("Subtitle lines must have a number before batching")
            line_numbers.append(line.number)

        duplicates = [str(number) for number, count in Counter(line_numbers).items() if count > 1]
        if duplicates:
            duplicate_list = ', '.join(sorted(duplicates, key=int))
            raise ValueError(f"Duplicate line numbers detected in scene {self._current_scene.number}: {duplicate_list}")

        self._accumulated_lines.sort(key=lambda line: line.number)

        # Use batcher's subdivision logic
        split_line_groups : list[list[SubtitleLine]] = self._batcher._split_lines(self._accumulated_lines)

        for i, line_group in enumerate(split_line_groups):
            batch_data : dict[str, Any] = {
                'scene': self._current_scene.number,
                'number': i + 1
            }

            batch = SubtitleBatch(batch_data)
            batch._originals = line_group
            self._current_scene.AddBatch(batch)
