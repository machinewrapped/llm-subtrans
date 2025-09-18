import logging
import time

try:
    import openai       # type: ignore

    from PySubtrans.Helpers.Localization import _
    from PySubtrans.Helpers.Parse import ParseDelayFromHeader
    from PySubtrans.Helpers import FormatMessages
    from PySubtrans.Translation import Translation
    from PySubtrans.TranslationClient import TranslationClient
    from PySubtrans.TranslationPrompt import TranslationPrompt
    from PySubtrans.SubtitleError import TranslationImpossibleError, TranslationResponseError
    from PySubtrans.Options import SettingsType

    class AzureOpenAIClient(TranslationClient):
        """
        Handles communication with AzureOpenAI to request translations
        """
        def __init__(self, settings : SettingsType):
            super().__init__(settings)

            if not hasattr(openai, "AzureOpenAI"):
                raise TranslationImpossibleError(_("The OpenAI library is out of date and must be updated"))

            if not self.api_key:
                raise TranslationImpossibleError(_("API key must be set in .env or provided as an argument"))

            if not self.api_base:
                raise TranslationImpossibleError(_("API base must be set in .env or provided as an argument"))

            if not self.api_version:
                raise TranslationImpossibleError(_("API version must be set in .env or provided as an argument"))

            if not self.deployment_name:
                raise TranslationImpossibleError(_("Deployment name must be set in .env or provided as an argument"))

            logging.info(_("Translating with Azure OpenAI deployment {deployment_name}, API-version {api_version}, API Base: {api_base}").format(
                deployment_name=self.deployment_name,
                api_version=self.api_version,
                api_base=self.api_base
            ))

            self.client = openai.AzureOpenAI(azure_endpoint=self.api_base, api_version=self.api_version, azure_deployment=self.deployment_name, api_key=self.api_key)

        @property
        def api_key(self) -> str|None:
            return self.settings.get_str( 'api_key')

        @property
        def api_base(self) -> str|None:
            return self.settings.get_str( 'api_base')

        @property
        def api_version(self) -> str|None:
            return self.settings.get_str( 'api_version')

        @property
        def deployment_name(self) -> str|None:
            return self.settings.get_str( 'deployment_name')

        @property
        def rate_limit(self) -> float|None:
            return self.settings.get_float( 'rate_limit')

        def _request_translation(self, prompt : TranslationPrompt, temperature : float|None = None) -> Translation|None:
            """
            Request a translation based on the provided prompt
            """
            logging.debug(f"Messages:\n{FormatMessages(prompt.messages)}")

            temperature = temperature or self.temperature
            reponse = self._send_messages(prompt.messages, temperature)

            translation = Translation(reponse) if reponse else None

            return translation

        def _send_messages(self, messages : list[dict[str,str]], temperature):
            """
            Make a request to the Azure OpenAI API to provide a translation
            """
            response = {}

            if not self.deployment_name:
                raise TranslationImpossibleError(_("Deployment name must be set in .env or provided as an argument"))

            for retry in range(self.max_retries + 1):
                if self.aborted:
                    return None

                try:
                    result = self.client.chat.completions.create(
                        model=self.deployment_name,
                        messages=messages, # type: ignore
                        temperature=temperature
                    )

                    if self.aborted:
                        return None

                    response['response_time'] = getattr(result, 'response_ms', 0)

                    if result.usage:
                        response['prompt_tokens'] = getattr(result.usage, 'prompt_tokens')
                        response['completion_tokens'] = getattr(result.usage, 'completion_tokens')
                        response['total_tokens'] = getattr(result.usage, 'total_tokens')

                    # We only expect one choice to be returned as we have 0 temperature
                    if result.choices:
                        choice = result.choices[0]
                        reply = result.choices[0].message

                        response['finish_reason'] = getattr(choice, 'finish_reason', None)
                        response['text'] = getattr(reply, 'content', None)
                    else:
                        raise TranslationResponseError(_("No choices returned in the response"), response=result)

                    # Return the response if the API call succeeds
                    return response

                except openai.RateLimitError as e:
                    retry_after = e.response.headers.get('x-ratelimit-reset-requests') or e.response.headers.get('Retry-After')
                    if retry_after:
                        retry_seconds = ParseDelayFromHeader(retry_after)
                        logging.warning(_("Rate limit hit, retrying in {retry_seconds} seconds...").format(
                            retry_seconds=retry_seconds
                        ))
                        time.sleep(retry_seconds)
                        continue
                    else:
                        raise TranslationImpossibleError(_("OpenAI account quota reached, please upgrade your plan"))

                except openai.APITimeoutError as e:
                    if retry < self.max_retries and not self.aborted:
                        sleep_time = self.backoff_time * 2.0**retry
                        logging.warning(_("OpenAI error {error}, retrying in {sleep_time}...").format(
                            error=str(e), sleep_time=sleep_time
                        ))
                        time.sleep(sleep_time)
                        continue

                except openai.APIConnectionError as e:
                    if not self.aborted:
                        raise TranslationImpossibleError(str(e), error=e)

                except Exception as e:
                    raise TranslationImpossibleError(_("Unexpected error communicating with OpenAI"), error=e)

            raise TranslationImpossibleError(_("Failed to communicate with provider after {max_retries} retries").format(
                max_retries=self.max_retries
            ))

        def _abort(self):
            self.client.close()
            return super()._abort()

except ImportError:
    logging.debug("OpenAI SDK not installed.")