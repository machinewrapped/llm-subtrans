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

    Provides a fluent API for creating scenes, batches, and lines without requiring
    deep knowledge of the internal scene/batch structure.
    """

    def __init__(self, max_batch_size : int = 100, min_batch_size : int = 1):
        """
        Initialize SubtitleBuilder.

        Parameters
        ----------
        subtitles : Subtitles|None
            An existing Subtitles instance to build upon. If None, creates a new empty instance.
        max_batch_size : int
            Maximum number of lines per batch. Lines will be automatically organized into batches
            using intelligent gap-based splitting.
        min_batch_size : int
            Minimum size for batches when splitting. Helps avoid very small batches.
        """
        self._scenes : list[SubtitleScene] = []
        self._current_scene : SubtitleScene|None = None
        self._current_line_number : int = 0
        self._scene_counter : int = len(self._scenes)
        self._max_batch_size : int = max_batch_size
        self._min_batch_size : int = min_batch_size
        self._accumulated_lines : list[SubtitleLine] = []
        self._settings : SettingsType = SettingsType({
            'max_batch_size': max_batch_size,
            'min_batch_size': min_batch_size,
        })

    def AddScene(self, summary : str|None = None, context : dict[str, Any]|None = None) -> 'SubtitleBuilder':
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

        self._scene_counter += 1

        scene_data : dict[str, Any] = {'number': self._scene_counter}
        if summary:
            scene_data['context'] = {'summary': summary}

        self._current_scene = SubtitleScene(scene_data)
        if context:
            self._current_scene.UpdateContext(context)

        self._scenes.append(self._current_scene)
        self._accumulated_lines = []

        return self

    def AddLine(self, line : SubtitleLine) -> 'SubtitleBuilder':
        """
        Add a SubtitleLine object to the current scene. Lines are accumulated and will be intelligently
        organized into batches when the scene is finalized.

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

    def ConstructLine(self, start : timedelta|str, end : timedelta|str, text : str, metadata : dict[str, Any]|None = None) -> 'SubtitleBuilder':
        """
        Construct a SubtitleLine from parameters and add it to the current scene.

        This is a convenience method that combines SubtitleLine.Construct() with AddLine().

        Parameters
        ----------
        number : int
            Line number (should be unique).
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
        Add multiple subtitle lines to the current scene. Lines are automatically organized into batches.

        Parameters
        ----------
        lines : list[SubtitleLine|tuple[timedelta|str, timedelta|str, str, dict]]
            Either a list of SubtitleLine instances or tuples (number, start, end, text).

        Returns
        -------
        SubtitleBuilder
            Returns self for method chaining.

        Raises
        ------
        ValueError
            If no scene has been added yet.
        """
        for line_data in lines:
            if isinstance(line_data, SubtitleLine):
                self.AddLine(line_data)
            elif isinstance(line_data, tuple):
                if len(line_data) == 3:
                    start, end, text = line_data
                    self.ConstructLine(start, end, text)
                elif len(line_data) == 4:
                    start, end, text, metadata = line_data
                    self.ConstructLine(start, end, text, metadata)
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
            The completed subtitles with scenes and batches.
        """
        # Finalize the current scene
        self._finalize_current_scene()

        # Trigger the scenes setter to update flattened lists
        subtitles = Subtitles()
        subtitles.scenes = self._scenes
        return subtitles

    def _finalize_current_scene(self) -> None:
        """
        Finalize the current scene by intelligently batching accumulated lines.
        """
        if not self._current_scene or not self._accumulated_lines:
            return

        batcher = SubtitleBatcher(self._settings)

        # Use batcher's intelligent splitting logic
        split_line_groups : list[list[SubtitleLine]] = batcher._split_lines(self._accumulated_lines)

        # Create batches from the intelligently split groups
        for i, line_group in enumerate(split_line_groups):
            batch_data : dict[str, Any] = {
                'scene': self._current_scene.number,
                'number': i + 1
            }

            batch = SubtitleBatch(batch_data)
            batch._originals = line_group
            self._current_scene.AddBatch(batch)