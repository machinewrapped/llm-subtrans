from collections.abc import Callable
from typing import Any, TypeAlias
from PySubtrans.TranslationPrompt import TranslationPrompt
from PySubtrans.Translation import Translation

StreamingCallback: TypeAlias = Callable[[Translation], None]|None

class TranslationRequest:
    """
    Encapsulates a translation request with its prompt, callback, and tracking data
    """
    def __init__(self, prompt : TranslationPrompt, streaming_callback : StreamingCallback = None):
        self.prompt : TranslationPrompt = prompt
        self.streaming_callback : StreamingCallback = streaming_callback

        # Progress tracking
        self.accumulated_text : str = ""
        self.last_processed_pos : int = 0

        # Additional context storage
        self.context : dict[str, Any] = {}

    @property
    def is_streaming(self) -> bool:
        """Check if this is a streaming request"""
        return self.streaming_callback is not None

    def ProcessStreamingDelta(self, delta_text : str) -> None:
        """Process a streaming delta and emit partial updates for complete sections"""
        if delta_text:
            self.accumulated_text += delta_text

        # Check for complete line groups (blank line threshold)
        if self._has_complete_line_group():
            self._emit_partial_update()

    def StoreContext(self, key : str, value : Any) -> None:
        """Store additional context data"""
        self.context[key] = value

    def GetContext(self, key : str, default : Any = None) -> Any:
        """Retrieve context data"""
        return self.context.get(key, default)

    def _has_complete_line_group(self) -> bool:
        """Check if there's a complete line group since last processed position"""
        new_content = self.accumulated_text[self.last_processed_pos:]
        return '\n\n' in new_content

    def _emit_partial_update(self) -> None:
        """Emit partial update for complete sections and mark them as processed"""
        if not self.streaming_callback:
            return

        # Find the last complete line group
        last_double_newline = self.accumulated_text.rfind('\n\n')
        if last_double_newline == -1:
            return

        # Extract complete section and emit update
        complete_section = self.accumulated_text[:last_double_newline + 2]
        if complete_section.strip():
            partial_translation = Translation({'text': complete_section})
            self.streaming_callback(partial_translation)

        # Mark as processed
        self.last_processed_pos = last_double_newline + 2
