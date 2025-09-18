from __future__ import annotations
from typing import TypeAlias

from PySubtrans.SubtitleBatch import SubtitleBatch
from PySubtrans.SubtitleLine import SubtitleLine
from PySubtrans.SubtitleScene import SubtitleScene
from PySubtrans.Translation import Translation
from PySubtrans.TranslationPrompt import TranslationPrompt

SceneKey = int
BatchKey = tuple[int, int]
LineKey = tuple[int, int, int]

Key : TypeAlias = SceneKey | BatchKey | LineKey
Value : TypeAlias = str | int | float | list[str] | dict[str, str|list|dict] | Translation | TranslationPrompt | None
UpdateValue : TypeAlias = dict[str, 'UpdateValue'] | dict[int, 'UpdateValue'] | Value
UpdateType : TypeAlias = dict[Key, UpdateValue]
ModelTypes : TypeAlias = SubtitleLine | SubtitleBatch | SubtitleScene

class ModelUpdateSection:
    def __init__(self):
        self.updates: UpdateType = {}
        self.replacements: dict[Key, ModelTypes] = {}
        self.additions: dict[Key, ModelTypes] = {}
        self.removals: list[SceneKey]|list[BatchKey]|list[LineKey]|list[int] = []

    def update(self, key: Key, item_update: UpdateValue) -> None:
        self.updates[key] = item_update

    def replace(self, key: Key, item: ModelTypes) -> None:
        self.replacements[key] = item

    def add(self, key: Key, item: ModelTypes) -> None:
        self.additions[key] = item

    def remove(self, key: Key) -> None:
        if any(type(existing_key) != type(key) for existing_key in self.removals):
            raise ValueError(f"All removal keys must be of the same type: {type(key)}")            
        self.removals.append(key) # type: ignore[list-item]

    @property
    def has_updates(self) -> bool:
        return bool(self.updates or self.replacements or self.additions or self.removals)

    @property
    def size_changed(self) -> bool:
        return bool(self.removals or self.additions)