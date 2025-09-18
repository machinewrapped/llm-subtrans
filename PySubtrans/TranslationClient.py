import logging
import time

from PySubtrans.Instructions import DEFAULT_TASK_TYPE
from PySubtrans.Options import Options, SettingsType
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import TranslationError
from PySubtrans.SubtitleLine import SubtitleLine
from PySubtrans.TranslationParser import TranslationParser
from PySubtrans.TranslationPrompt import TranslationPrompt, default_prompt_template
from PySubtrans.Translation import Translation

linesep = '\n'

class TranslationClient:
    """
    Handles communication with the translation provider
    """
    def __init__(self, settings : SettingsType):
        if isinstance(settings, Options):
            settings = settings.GetSettings()

        self.settings: SettingsType = SettingsType(settings)
        self.instructions: str|None = settings.get_str('instructions')
        self.retry_instructions: str|None = settings.get_str('retry_instructions')
        self.aborted: bool = False

        if not self.instructions:
            raise TranslationError("No instructions provided for the translator")

    @property
    def supports_conversation(self) -> bool:
        return self.settings.get_bool('supports_conversation', False)

    @property
    def supports_system_prompt(self) -> bool:
        return self.settings.get_bool('supports_system_prompt', False)

    @property
    def supports_system_messages(self) -> bool:
        return self.settings.get_bool('supports_system_messages', False)

    @property
    def supports_system_messages_for_retry(self) -> bool:
        return self.settings.get_bool('supports_system_messages_for_retry', self.supports_system_messages)

    @property
    def system_role(self) -> str:
        return self.settings.get_str('system_role') or "system"

    @property
    def prompt_template(self) -> str:
        return self.settings.get_str('prompt_template') or default_prompt_template

    @property
    def rate_limit(self) -> float|None:
        return self.settings.get_float('rate_limit')

    @property
    def temperature(self) -> float:
        return self.settings.get_float('temperature') or 0.0

    @property
    def max_retries(self) -> int:
        return self.settings.get_int('max_retries') or 3

    @property
    def backoff_time(self) -> float:
        return self.settings.get_float('backoff_time') or 5.0

    def BuildTranslationPrompt(self, user_prompt : str, instructions : str, lines : list[SubtitleLine], context : dict) -> TranslationPrompt:
        """
        Generate a translation prompt for the context
        """
        prompt = TranslationPrompt(user_prompt, self.supports_conversation)
        prompt.supports_system_prompt = self.supports_system_prompt
        prompt.supports_system_messages = self.supports_conversation and self.supports_system_messages
        prompt.supports_system_messages_for_retry = self.supports_system_messages_for_retry
        prompt.system_role = self.system_role
        prompt.prompt_template = self.prompt_template
        prompt.GenerateMessages(instructions, lines, context)
        return prompt

    def RequestTranslation(self, prompt : TranslationPrompt, temperature : float|None = None) -> Translation|None:
        """
        Generate the messages to request a translation
        """
        start_time = time.monotonic()

        # Perform the translation
        translation = self._request_translation(prompt, temperature)

        if self.aborted or translation is None:
            return None

        if translation.text:
            logging.debug(f"Response:\n{translation.text}")

        # If a rate limit is replied ensure a minimum duration for each request
        rate_limit = self.rate_limit
        if rate_limit and rate_limit > 0.0:
            minimum_duration = 60.0 / rate_limit

            elapsed_time = time.monotonic() - start_time
            if elapsed_time < minimum_duration:
                sleep_time = minimum_duration - elapsed_time
                logging.debug(f"Sleeping for {sleep_time:.2f} seconds to respect rate limit")
                time.sleep(sleep_time)

        return translation

    def GetParser(self, task_type: str = DEFAULT_TASK_TYPE) -> TranslationParser:
        """
        Return a parser that can process the provider's response
        """
        return TranslationParser(task_type, self.settings)  # type: ignore

    def AbortTranslation(self) -> None:
        self.aborted = True
        self._abort()
        pass

    def _request_translation(self, prompt : TranslationPrompt, temperature : float|None = None) -> Translation|None:
        """
        Make a request to the API to provide a translation
        """
        _ = prompt, temperature  # Mark as accessed to avoid lint warnings
        raise NotImplementedError

    def _abort(self) -> None:
        # Try to terminate ongoing requests
        pass
