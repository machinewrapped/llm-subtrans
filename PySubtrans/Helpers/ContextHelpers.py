from __future__ import annotations

from typing import Any, TYPE_CHECKING

from PySubtrans.Helpers.Parse import ParseNames
from PySubtrans.SubtitleError import SubtitleError

if TYPE_CHECKING:
    from PySubtrans.Subtitles import Subtitles


def GetBatchContext(subtitles: Subtitles, scene_number: int, batch_number: int, max_lines: int|None = None) -> dict[str, Any]:
    """
    Get context for a batch of subtitles, by extracting summaries from previous scenes and batches
    """
    with subtitles.lock:
        scene = subtitles.GetScene(scene_number)
        if not scene:
            raise SubtitleError(f"Failed to find scene {scene_number}")

        batch = subtitles.GetBatch(scene_number, batch_number)
        if not batch:
            raise SubtitleError(f"Failed to find batch {batch_number} in scene {scene_number}")

        context : dict[str,Any] = {
            'scene_number': scene.number,
            'batch_number': batch.number,
            'scene': f"Scene {scene.number}: {scene.summary}" if scene.summary else f"Scene {scene.number}",
            'batch': f"Batch {batch.number}: {batch.summary}" if batch.summary else f"Batch {batch.number}"
        }

        if 'movie_name' in subtitles.settings:
            context['movie_name'] = subtitles.settings.get_str('movie_name')

        if 'description' in subtitles.settings:
            context['description'] = subtitles.settings.get_str('description')

        if 'names' in subtitles.settings:
            context['names'] = ParseNames(subtitles.settings.get('names', []))

        history_lines = GetHistory(subtitles, scene_number, batch_number, max_lines)

        if history_lines:
            context['history'] = history_lines

    return context


def GetHistory(subtitles: Subtitles, scene_number: int, batch_number: int, max_lines: int|None = None) -> list[str]:
    """
    Get a list of historical summaries up to a given scene and batch number
    """
    history_lines : list[str] = []
    last_summary : str = ""

    scenes = [scene for scene in subtitles.scenes if scene.number and scene.number < scene_number]
    for scene in [scene for scene in scenes if scene.summary]:
        if scene.summary != last_summary:
            history_lines.append(f"scene {scene.number}: {scene.summary}")
            last_summary = scene.summary or ""

    batches = [batch for batch in subtitles.GetScene(scene_number).batches if batch.number is not None and batch.number < batch_number]
    for batch in [batch for batch in batches if batch.summary]:
        if batch.summary != last_summary:
            history_lines.append(f"scene {batch.scene} batch {batch.number}: {batch.summary}")
            last_summary = batch.summary or ""

    if max_lines:
        history_lines = history_lines[-max_lines:]

    return history_lines
