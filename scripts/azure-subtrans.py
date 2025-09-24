import os
import logging

from check_imports import check_required_imports
check_required_imports(['PySubtrans', 'openai'], 'azure')

from scripts.subtrans_common import (
    InitLogger,
    CreateArgParser,
    CreateOptions,
    CreateProject,
)
from PySubtrans import init_translator
from PySubtrans.Options import Options
from PySubtrans.SubtitleProject import SubtitleProject

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
    options : Options = CreateOptions(
        args,
        provider,
        deployment_name=args.deploymentname or deployment_name,
        api_base=args.apibase or api_base,
        api_version=args.apiversion or api_version,
    )

    # Create a project for the translation
    project : SubtitleProject = CreateProject(options, args)

    # Translate the subtitles
    translator = init_translator(options)
    project.TranslateSubtitles(translator)

    if project.use_project_file:
        logging.info(f"Writing project data to {str(project.projectfile)}")
        project.SaveProjectFile()

except Exception as e:
    print("Error:", e)
    raise
