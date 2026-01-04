import logging

import boto3 # type: ignore[import]

from PySubtrans.Helpers import FormatMessages
from PySubtrans.Helpers.Localization import _
from PySubtrans.Options import SettingsType

from PySubtrans.Translation import Translation
from PySubtrans.TranslationClient import TranslationClient
from PySubtrans.TranslationRequest import TranslationRequest
from PySubtrans.SubtitleError import TranslationImpossibleError, TranslationResponseError

class BedrockClient(TranslationClient):
    """
    Handles communication with Amazon Bedrock to request translations
    """
    def __init__(self, settings : SettingsType):
        super().__init__(settings)

        self._emit_info(_("Translating with Bedrock model {model_id}, using region: {aws_region}").format(
            model_id=self.model_id, aws_region=self.aws_region
        ))

        self.client = boto3.client(
            'bedrock-runtime',
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_access_key,
            region_name=self.aws_region
        )

    @property
    def access_key(self) -> str|None:
        return self.settings.get_str( 'access_key')

    @property
    def secret_access_key(self) -> str|None:
        return self.settings.get_str( 'secret_access_key')

    @property
    def aws_region(self) -> str|None:
        return self.settings.get_str( 'aws_region')

    @property
    def model_id(self) -> str|None:
        return self.settings.get_str( 'model')

    @property
    def max_tokens(self) -> int:
        return self.settings.get_int( 'max_tokens') or 4096

    def _request_translation(self, request: TranslationRequest, temperature: float|None = None) -> Translation|None:
        """
        Request a translation based on the provided prompt
        """
        if not self.access_key:
            raise TranslationImpossibleError(_("Access key must be set in .env or provided as an argument"))

        if not self.secret_access_key:
            raise TranslationImpossibleError(_("Secret access key must be set in .env or provided as an argument"))

        if not self.aws_region:
            raise TranslationImpossibleError(_("AWS region must be set in .env or provided as an argument"))

        if not self.model_id:
            raise TranslationImpossibleError(_("Model ID must be provided as an argument"))

        if not request.prompt.system_prompt:
            raise TranslationImpossibleError(_("No system prompt provided"))

        logging.debug(f"Messages:\n{FormatMessages(request.prompt.messages)}")

        content = _structure_messages(request.prompt.messages)

        if not content or not isinstance(request.prompt.content, list):
            raise TranslationImpossibleError(_("No content provided for translation"))

        reponse = self._send_messages(request.prompt.system_prompt, content, temperature=temperature)

        translation = Translation(reponse) if reponse else None

        return translation

    def _send_messages(self, system_prompt : str, messages : list[dict], temperature : float|None = None) -> dict|None:
        """
        Make a request to the Amazon Bedrock API to provide a translation
        """
        if self.aborted:
            return None

        try:
            inference_config = {
                    'temperature' : temperature or 0.0,
                    'maxTokens' : self.max_tokens
                }

            if self.supports_system_prompt and system_prompt:
                result = self.client.converse(
                    modelId=self.model_id,
                    messages=messages,
                    system = [{ 'text' : system_prompt }],
                    inferenceConfig = inference_config
                    )
            else:
                result = self.client.converse(
                    modelId=self.model_id,
                    messages=messages,
                    inferenceConfig = inference_config
                    )

            if self.aborted:
                return None

            output = result.get('output')

            if not output:
                raise TranslationResponseError(_("No output returned in the response"), response=result)

            response = {}

            if 'stopReason' in result:
                response['finish_reason'] = result['stopReason']

            if 'usage' in result:
                response['prompt_tokens'] = result['usage'].get('inputTokens')
                response['output_tokens'] = result['usage'].get('outputTokens')
                response['total_tokens'] = result['usage'].get('totalTokens')

            message = output.get('message')
            if message and message.get('role') == 'assistant':
                text = [ content.get('text') for content in message.get('content',[]) ]
                response['text'] = '\n'.join(text)

            # Return the response if the API call succeeds
            return response

        except Exception as e:
            raise TranslationImpossibleError(_("Error communicating with Bedrock: {error}").format(
                error=str(e)
            ), error=e)

def _structure_messages(messages : list[dict[str,str]]) -> list[dict]:
    """
    Structure the messages to be sent to the API
    """
    return [
        {
            'role' : message['role'],
            'content' : [{ 'text': message['content'] }]
        }
        for message in messages]
