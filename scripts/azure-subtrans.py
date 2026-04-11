import logging
import os

from check_imports import check_required_imports
check_required_imports(['PySubtrans', 'openai'], 'azure')

from scripts.subtrans_common import (
    InitLogger,
    CreateArgParser,
    CreateOptions,
    CreateProject,
    TranslateProject,
)


# Update when newer ones are available - https://learn.microsoft.com/en-us/azure/ai-services/openai/reference
latest_azure_api_version = "2024-02-01"

provider = "Azure"
deployment_name = os.getenv('AZURE_DEPLOYMENT_NAME')
api_base = os.getenv('AZURE_API_BASE')
api_version = os.getenv('AZURE_API_VERSION', "2024-02-01")

parser = CreateArgParser(f"Translates subtitles using a model on an OpenAI Azure deployment")
parser.add_argument('-k', '--apikey', type=str, default=None, help=f"API key for your deployment")
parser.add_argument('-b', '--apibase', type=str, default=None, help="API backend base address.")
parser.add_argument('-a', '--apiversion', type=str, default=None, help="Azure API version")
parser.add_argument('--deploymentname', type=str, default=None, help="Azure deployment name")
args = parser.parse_args()

logger_options = InitLogger("azure-subtrans", args.debug)

try:
    options = CreateOptions(
        args,
        provider,
        deployment_name=args.deploymentname or deployment_name,
        api_base=args.apibase or api_base,
        api_version=args.apiversion or api_version,
    )
    project = CreateProject(options, args)
    TranslateProject(project, options, verbose=args.verbose, preview=args.preview)

except Exception as e:
    logging.error(f"Error during subtitle translation: {e}")
    raise
