from json import JSONDecodeError
import logging
import time
from typing import Any

from PySubtrans.Helpers.Localization import _
from PySubtrans.Helpers.Parse import ParseDelayFromHeader
from PySubtrans.Options import SettingsType
from PySubtrans.SubtitleError import TranslationResponseError

try:
    import openai   # type: ignore
    import httpx

    from PySubtrans.Helpers import FormatMessages
    from PySubtrans.SubtitleError import TranslationError, TranslationImpossibleError
    from PySubtrans.Translation import Translation
    from PySubtrans.TranslationClient import TranslationClient
    from PySubtrans.TranslationPrompt import TranslationPrompt

    class OpenAIClient(TranslationClient):
        """
        Handles communication with OpenAI to request translations
        """
        def __init__(self, settings : SettingsType):
            super().__init__(settings)

            if not hasattr(openai, "OpenAI"):
                raise TranslationImpossibleError(_("The OpenAI library is out of date and must be updated"))

            openai.api_key = self.api_key or openai.api_key

            if not openai.api_key:
                raise TranslationImpossibleError(_("API key must be set in .env or provided as an argument"))

            logging.info(_("Translating with model {model}, Using API Base: {api_base}").format(
                model=self.model or _("default"), 
                api_base=self.api_base or openai.base_url
            ))

            self.client: openai.OpenAI|None = None

        @property
        def api_key(self) -> str|None:
            return self.settings.get_str( 'api_key')

        @property
        def api_base(self) -> str|None:
            return self.settings.get_str( 'api_base')

        @property
        def model(self) -> str|None:
            return self.settings.get_str( 'model')
        
        @property
        def reuse_client(self) -> bool:
            return self.settings.get_bool( 'reuse_client', True)

        def _request_translation(self, prompt : TranslationPrompt, temperature : float|None = None) -> Translation|None:
            """
            Request a translation based on the provided prompt
            """
            logging.debug(f"Messages:\n{FormatMessages(prompt.messages)}")

            # If we're using a new client for each request, create it here
            temperature = temperature or self.temperature

            response = self._try_send_messages(prompt, temperature)

            translation = Translation(response) if response else None

            if translation:
                if translation.quota_reached:
                    raise TranslationImpossibleError(_("Account quota reached, please upgrade your plan or wait until it renews"))

                if translation.reached_token_limit:
                    raise TranslationError(_("Too many tokens in translation"), translation=translation)

            return translation

        def _send_messages(self, prompt: TranslationPrompt, temperature : float) -> dict[str, Any]|None:
            """
            Communicate with the API
            """
            raise NotImplementedError

        def _abort(self) -> None:
            if self.client:
                self.client.close()
            return super()._abort()
        
        def _try_send_messages(self, prompt : TranslationPrompt, temperature: float) -> dict[str, Any]|None:
            for retry in range(self.max_retries + 1):
                if self.aborted:
                    return None

                backoff_time = self.backoff_time * 2.0**retry

                try:
                    if not self.client or not self.reuse_client:
                        self._create_client()

                    response = self._send_messages(prompt, temperature)

                    return response
                
                except TranslationResponseError as e:
                    if retry < self.max_retries and not self.aborted:
                        logging.warning(_("Translation response error: {error}, retrying in {backoff_time} seconds...").format(
                            error=str(e), backoff_time=backoff_time
                        ))
                        time.sleep(backoff_time)
                        continue

                except openai.RateLimitError as e:
                    if not self.aborted:
                        retry_after = e.response.headers.get('x-ratelimit-reset-requests') or e.response.headers.get('Retry-After')
                        if retry_after:
                            backoff_time = ParseDelayFromHeader(retry_after)
                            logging.warning(_("Rate limit hit, retrying in {backoff_time} seconds...").format(
                                backoff_time=backoff_time
                            ))
                            time.sleep(backoff_time)
                            continue
                        else:
                            raise TranslationImpossibleError(_("Account quota reached, please upgrade your plan"))

                except openai.APITimeoutError as e:
                    if retry < self.max_retries and not self.aborted:
                        logging.warning(_("API Timeout, retrying in {backoff_time} seconds...").format(
                            backoff_time=backoff_time
                        ))
                        time.sleep(backoff_time)
                        continue

                except JSONDecodeError as e:
                    if retry < self.max_retries and not self.aborted:
                        logging.warning(_("Invalid response received, retrying in {backoff_time} seconds...").format(
                            backoff_time=backoff_time
                        ))
                        time.sleep(backoff_time)
                        continue

                except openai.APIConnectionError as e:
                    if not self.aborted:
                        raise TranslationError(str(e), error=e)

                except Exception as e:
                    raise TranslationImpossibleError(_("Unexpected error communicating with the provider"), error=e)

            if not self.aborted:
                raise TranslationImpossibleError(_("Failed to communicate with provider after {max_retries} retries").format(
                    max_retries=self.max_retries
                ))

        def _create_client(self) -> None:
            http_client: httpx.Client|None = None
            proxy = self.settings.get_str( 'proxy')
            if proxy:
                # Use httpx with SOCKS proxy support
                proxies = {
                    'http://': proxy,
                    'https://': proxy
                }
                http_client = httpx.Client(proxies=proxies) #type: ignore

            elif self.settings.get_bool( 'use_httpx'):
                if self.api_base is None:
                    raise TranslationImpossibleError(_("API base must be set when using httpx"))

                http_client = httpx.Client(base_url=self.api_base, follow_redirects=True)

            self.client = openai.OpenAI(api_key=openai.api_key, base_url=self.api_base or None, http_client=http_client)

except ImportError as e:
    logging.debug(f"Failed to import openai: {e}")
