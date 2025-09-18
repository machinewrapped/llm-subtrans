import importlib.util
import logging
import os

from PySubtrans.Helpers.Localization import _
from PySubtrans.Options import SettingsType
from PySubtrans.SettingsType import GuiSettingsType, SettingsType

if not importlib.util.find_spec("boto3"):
    logging.info(_("Amazon Boto3 SDK is not installed. Bedrock provider will not be available"))
else:
    try:
        import boto3 # type: ignore[import]

        from PySubtrans.Helpers.Localization import _


        from PySubtrans.Providers.Bedrock.BedrockClient import BedrockClient
        from PySubtrans.TranslationClient import TranslationClient
        from PySubtrans.TranslationProvider import TranslationProvider

        class BedrockProvider(TranslationProvider):
            name = "Bedrock"

            information = """
            <p>Bedrock API provider.</p>
            <p>NOTE: Amazon Bedrock is not recommended for most users. The setup is complex, and model capabilities can be unpredictable - some models do not fulfil translation requests.</p>
            <p>To use Bedrock as a provider you need to provide an access key and secret access key. This involves setting up an IAM user in the AWS console and <a href="https://docs.aws.amazon.com/bedrock/latest/userguide/model-access-modify.html">enabling model access</a> for them.</p>
            <p>You must also specify an AWS region to use for requests - this will affect the available models.</p>
            """

            def __init__(self, settings : SettingsType):
                super().__init__(self.name, SettingsType({
                    "access_key": settings.get_str('access_key', os.getenv('AWS_ACCESS_KEY_ID')),
                    "secret_access_key": settings.get_str('secret_access_key', os.getenv('AWS_SECRET_ACCESS_KEY')),
                    "aws_region": settings.get_str('aws_region', os.getenv('AWS_REGION', 'eu-west-1')),
                    "model": settings.get_str('model', 'Amazon-Titan-Text-G1'),
                    "max_tokens": settings.get_int('max_tokens', 8192),
                    #TODO: add options for supports system messages and prompt?
                    'temperature': settings.get_float('temperature', 0.0),
                    "rate_limit": settings.get_float('rate_limit')
                }))

                self.refresh_when_changed = ['access_key', 'secret_access_key', 'aws_region']
                self._regions = None

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
            def regions(self) -> list[str]:
                if not self._regions:
                    self._regions = self.get_aws_regions()
                return self._regions

            def GetTranslationClient(self, settings : SettingsType) -> TranslationClient:
                client_settings = SettingsType(self.settings.copy())
                client_settings.update(settings)
                client_settings.update({
                    'supports_conversation': True,
                    'supports_system_messages': False,
                    'supports_system_prompt': False             # Apparently some models do?
                    })
                return BedrockClient(client_settings)

            def GetOptions(self, settings : SettingsType) -> GuiSettingsType:
                options : GuiSettingsType = {
                    'access_key': (str, _("An AWS access key is required")),
                    'secret_access_key': (str, _("An AWS secret access key is required")),
                }

                regions = self.regions
                if not regions:
                    options['aws_region'] = (str, _("The AWS region to use for requests must be specified."))
                else:
                    options['aws_region'] = (regions, "The AWS region to use for requests.")

                if self.access_key and self.secret_access_key and self.aws_region:
                    models = self.available_models or ["Unable to retrieve model list"]
                    options.update({
                        'model': (models, "AI model to use as the translator. Model access must be enabled in the AWS Console. Some models may not translate the subtitles."),
                        'max_tokens': (int, _("The maximum number of tokens to generate in a single request")),
                        'rate_limit': (float, _("The maximum number of requests to make per minute"))
                    })
                return options

            def GetInformation(self) -> str:
                information = self.information
                if not self.ValidateSettings():
                    information = information + f"<p>{self.validation_message}</p>"
                return information

            def GetAvailableModels(self) -> list[str]:
                """
                Returns a list of possible values for the model
                """
                try:
                    if not self.access_key or not self.secret_access_key:
                        logging.debug("AWS access keys not provided")
                        return []

                    client = boto3.client(
                        'bedrock',
                        aws_access_key_id=self.access_key,
                        aws_secret_access_key=self.secret_access_key,
                        region_name=self.aws_region
                    )

                    response = client.list_foundation_models()

                    if not response or 'modelSummaries' not in response:
                        return []

                    model_details = response['modelSummaries']

                    # Define valid statuses for filtering
                    valid_status = ['ACTIVE','AVAILABLE']

                    # Filter for translation models that are in the valid statuses
                    translation_models = [
                        model['modelId']
                        for model in model_details
                            if 'TEXT' in model.get('inputModalities', []) and model.get('modelLifecycle', []).get('status') in valid_status
                    ]

                    # If no translation-specific models are available, fall back to all available models
                    model_list = translation_models or [ model['modelId'] for model in model_details]

                    # Return sorted list of model IDs
                    return sorted(model_list)

                except Exception as e:
                    logging.error(_("Unable to retrieve available AI models: {error}").format(
                        error=str(e)
                    ))
                    return []

            def ValidateSettings(self) -> bool:
                """
                Validate the settings for the provider
                """
                if not self.access_key:
                    self.validation_message = "AWS access key is required"
                    return False

                if not self.secret_access_key:
                    self.validation_message = "AWS secret access key is required"
                    return False

                if not self.aws_region:
                    self.validation_message = "AWS region is required"
                    return False

                return True

            def _allow_multithreaded_translation(self) -> bool:
                """
                Assume the Bedrock provider can handle multiple requests
                """
                return True

            def get_aws_regions(self) -> list[str]:
                """
                Fetches a list of AWS regions that support Bedrock from the boto3 SDK (may become out of date)
                """
                try:
                    session = boto3.session.Session()
                    bedrock_regions = session.get_available_regions("bedrock")
                    return sorted(bedrock_regions)
                except Exception as e:
                    print(f"Error fetching AWS regions: {e}")
                    return []

    except ImportError:
        logging.info(_("Amazon Boto3 SDK is not installed. Bedrock provider will not be available"))
