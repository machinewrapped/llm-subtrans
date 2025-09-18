from typing import Any

from PySubtrans.Helpers.Localization import _
from PySubtrans.SubtitleError import SubtitleError, TranslationError
from PySubtrans.SubtitleLine import SubtitleLine

default_prompt_template: str = "<context>\n{context}\n</context>\n\n{prompt}\n\n<summary>Summary of the batch</summary>\n<scene>Summary of the scene</scene>\n"
default_line_template: str = "#{number}\nOriginal>\n{text}\nTranslation>\n"
default_tag_template: str = "<{tag}>{content}</{tag}>"
default_context_tags: list[str] = ['description', 'names', 'history', 'scene', 'summary', 'batch']

class TranslationPrompt:
    """
    Class for formatting a prompt to request translation of a batch of subtitles
    """
    def __init__(self, user_prompt: str, conversation: bool = True):
        """
        Construct a translation prompt for a batch of subtitles
        """
        # User prompt to include at the top of the prompt
        self.user_prompt: str = user_prompt

        # Flag controlling whether the prompt content is formatted as a list of messages for a conversational model
        self.conversation: bool = conversation

        # Flag controlling whether to include a system prompt
        self.supports_system_prompt: bool = False

        # Flag controlling whether to include messages in the "system" role
        self.supports_system_messages: bool = False

        # Name of the privileged role to use when supports_system_messages is True
        self.system_role: str = "system"

        # Flag controlling whether to use the "system" role for retry instructions
        self.supports_system_messages_for_retry: bool = False

        # Templates for formatting the prompt - override these to customize the prompt
        self.prompt_template: str = default_prompt_template
        self.line_template: str = default_line_template
        self.tag_template: str = default_tag_template
        self.context_tags: list[str] = default_context_tags

        self.system_prompt: str|None = None
        self.batch_prompt: str|None = None
        self.content: str|list[str]|list[dict[str, str]]|None = None
        self.messages: list[dict[str, str]] = []

    def GenerateMessages(self, instructions: str, lines: list[SubtitleLine], context: dict[str, Any]) -> None:
        """
        Generate the messages to request translation of a batch of subtitles

        :param instructions: instructions to provide to the translator
        :param lines: list of lines to translate
        :param context: dictionary of contextual information to include in the prompt
        """
        self.messages.clear()

        user_role = "user"
        system_role = self.system_role if self.supports_system_messages else user_role

        self.batch_prompt = self.GenerateBatchPrompt(lines, context=context)

        if not instructions:
            self.messages.append({'role': user_role, 'content': self.batch_prompt})
        elif self.supports_system_prompt:
            self.system_prompt = instructions
            self.messages.append({'role': user_role, 'content': self.batch_prompt})
        elif self.supports_system_messages:
            self.messages.append({'role': system_role, 'content': instructions})
            self.messages.append({'role': user_role, 'content': self.batch_prompt})
        else:
            user_instructions = self._wrap_system_message(instructions)
            self.messages.append({'role': user_role, 'content': f"{user_instructions}\n{self.batch_prompt}"})

        self._generate_content()

    def GenerateBatchPrompt(self, lines: list[SubtitleLine], context: dict[str, Any]|None = None) -> str:
        """
        Create the user prompt for translating a set of lines

        :param tag_lines: optional list of extra lines to include at the top of the prompt.
        :param template: optional template to format the prompt.
        """
        if not lines:
            raise TranslationError("No source lines provided")

        source_lines: list[str|None] = [ _get_line_prompt(line, self.line_template) for line in lines ]

        real_lines = [line for line in source_lines if line is not None]

        if not real_lines:
            raise ValueError("No valid source lines to translate")

        prompt = '\n\n'.join(real_lines).strip()

        if self.user_prompt:
            prompt = f"{self.user_prompt}\n\n{prompt}\n"

        tag_lines = _generate_tag_lines(context, self.context_tags, self.tag_template) if context else ""

        if tag_lines:
            prompt = self.prompt_template.format(prompt=prompt, context=tag_lines)

        return prompt

    def GenerateRetryPrompt(self, reponse : str, retry_instructions : str, errors : list[SubtitleError|str]|None) -> None:
        """
        Request retranslation of lines that were not translated originally
        """
        messages = []

        user_role = "user"
        assistant_role = "assistant"
        system_role = self.system_role if self.supports_system_messages_for_retry else user_role

        for message in self.messages:
            messages.append(message)
            if message.get('role') == user_role:
                break

        messages.append({ 'role': assistant_role, 'content': reponse })

        if errors:
            unique_errors = set(( f"- {str(e).strip()}" for e in errors if isinstance(e, TranslationError) ))
            error_list = list(unique_errors)
            error_message = '\n'.join(error_list)
            retry_prompt = f"There were some problems with the translation:\n{error_message}\n\nPlease correct them."
        else:
            # Maybe less is more?
            retry_prompt = "There were some problems with the translation. Please try again."

        if self.supports_system_messages:
            messages.append({ 'role': system_role, 'content': retry_instructions })
        else:
            retry_prompt = f"{self._wrap_system_message(retry_instructions)}\n{retry_prompt}"

        messages.append({ 'role': user_role, 'content': retry_prompt })

        self.messages = messages
        self._generate_content()

    def _wrap_system_message(self, message : str) -> str:
        separator = "--------"
        return '\n'.join( [ separator, "SYSTEM", separator, message.strip(), separator])

    def _generate_content(self) -> None:
        self.content = self.messages if self.conversation else self._generate_completion()

    def _generate_completion(self) -> str:
        """ Convert a series of messages to a script for the AI to complete """
        if not self.messages:
            raise TranslationError(_("No content provided for translation"))

        if self.supports_system_messages:
            return "\n\n".join([ f"#{m.get('role')} ###\n{m.get('content')}" for m in self.messages ])
        else:
            return "\n\n".join([ str(m.get('content')) for m in self.messages if m.get('content') is not None ])

def _get_line_prompt(line : SubtitleLine, line_template : str|None = None) -> str|None:
    """
    Generate a prompt for a single subtitle line
    """
    if not line.text or not line._index:
        return None

    if line_template is None:
        raise TranslationError(_("No line template provided"))

    return line_template.format(number=line.number, text=line.text_normalized)

def _generate_tag(tag : str, content : str|list[str], tag_template : str) -> str:
    """
    Generate tag with content using the provided template
    """
    if isinstance(content, list):
        content = ', '.join(content)

    return tag_template.format(tag=tag, content=content).strip()

def _generate_tag_lines(context : dict[str, Any], tags : list[str], tag_template : str) -> str|None:
    """
    Create a user message for specifying a set of tags

    :param context: dictionary of tag, value pairs
    :param tags: list of tags to extract from the context.
    :param tag_template: template to use for each tag
    """
    tag_lines = [ _generate_tag(tag, context[tag], tag_template) for tag in tags if context.get(tag) ]

    if not tag_lines:
        return None

    return '\n'.join([ tag for tag in tag_lines if tag ])

