import logging
from PySubtrans.Helpers.Text import ExtractTag, ExtractTagList
from PySubtrans.Substitutions import Substitutions

def ExtractTagSafely(tag : str, text : str) -> tuple[str, str|None]:
    """
    Extract a tag from text content, warn if there is an error
    """
    try:
        return ExtractTag(tag, text)
    except ValueError as e:
        logging.warning(f"Error extracting {tag} from translation: {e}")
        return text, None

def ExtractTagListSafely(tag : str, text : str) -> tuple[str, list[str]]:
    """
    Extract a tag list from text content, warn if there is an error
    """
    try:
        return ExtractTagList(tag, text)

    except ValueError as e:
        logging.warning(f"Error extracting {tag} from translation: {e}")
        return text, []

class Translation:
    def __init__(self, content : dict):
        self.content : dict = content or {}
        translation_text : str = content.get('text', '')
        self._text, context = self.ParseTranslation(translation_text)
        self.content.update(context)

    @property
    def text(self) -> str|None:
        return self._text.strip() if self._text else None

    @property
    def has_translation(self) -> bool:
        return True if self.text else False

    @property
    def summary(self) -> str|None:
        return self.content.get('summary')

    @property
    def scene(self) -> str|None:
        return self.content.get('scene')

    @property
    def synopsis(self) -> str|None:
        return self.content.get('synopsis')

    @property
    def names(self) -> str|list[str]|None:
        return self.content.get('names')

    @property
    def reasoning(self) -> str|None:
        return self.content.get('reasoning')

    @property
    def finish_reason(self) -> str|None:
        return self.content.get('finish_reason')

    @property
    def response_time(self) -> float|str|None:
        return self.content.get('response_time')

    @property
    def reached_token_limit(self) -> bool:
        return self.finish_reason == "length"

    @property
    def quota_reached(self) -> bool:
        return self.finish_reason == "quota_reached"

    @property
    def full_text(self) -> str|None:
        return self.content.get('text', self._text)

    def PerformSubstitutions(self, substitutions : Substitutions) -> None:
        """
        Apply any text substitutions to summary, scene, names and synopsis if they exist.

        Does NOT apply them to the translation text.
        """
        if self.summary:
            self.content['summary'] = substitutions.PerformSubstitutions(self.summary)
        if self.scene:
            self.content['scene'] = substitutions.PerformSubstitutions(self.scene)
        if self.synopsis:
            self.content['synopsis'] = substitutions.PerformSubstitutions(self.synopsis)

    def FormatResponse(self, include_text : bool = True) -> str:
        """
        Format the response for display
        """
        if not self.content:
            return "No translation"

        content_keys = [k for k in self.content.keys() if k not in ['text', 'summary', 'scene', 'names', 'reasoning']]
        metadata = [ f"{k}: {self.content[k]}" for k in content_keys if self.content.get(k) ]

        if self.scene:
            metadata.append(f"\nScene:\n{self.scene}")

        if self.summary:
            metadata.append(f"\nSummary:\n{self.summary}")

        if self.names:
            names = "\n".join(self.names)
            metadata.append(f"\n\nNames:\n{names}")

        if metadata:
            metadata_text = '\n'.join(metadata)
            return f"{metadata_text}\n\n{self.text}" if include_text else metadata_text
        else:
            return self.text if include_text and self.text else "No metadata available"

    def ParseTranslation(self, text : str) -> tuple[str, dict[str, str|list[str]|None]]:
        """
        Extract tags from text body
        """
        text, summary = ExtractTagSafely("summary", text)
        text, synopsis = ExtractTagSafely("synopsis", text)
        text, scene = ExtractTagSafely("scene", text)
        text, names = ExtractTagListSafely("names", text)

        context = {
            'summary': summary,
            'scene': scene,
            'synopsis': synopsis,
            'names': names
        }
        return text, context

