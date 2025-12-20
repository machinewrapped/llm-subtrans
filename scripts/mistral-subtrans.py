import os
import logging

from check_imports import check_required_imports
check_required_imports(['PySubtrans', 'mistralai'], 'mistral')

from scripts.subtrans_common import (
    InitLogger,
    CreateArgParser,
    CreateOptions,
    CreateProject,
)

from PySubtrans import init_translator
from PySubtrans.Options import Options
from PySubtrans.SubtitleProject import SubtitleProject

provider = "Mistral"
default_model = os.getenv('MISTRAL_MODEL') or "open-mistral-nemo"

parser = CreateArgParser(f"Translates subtitles using an Mistral model")
parser.add_argument('-k', '--apikey', type=str, default=None, help=f"Your Mistral API Key (https://console.mistral.ai/api-keys/)")
parser.add_argument('-m', '--model', type=str, default=None, help="The model to use for translation")
parser.add_argument('--server_url', type=str, default=None, help="Server URL (leave blank for default).")
args = parser.parse_args()

logger_options = InitLogger("mistral-subtrans", args.debug)

try:
    options : Options = CreateOptions(
        args,
        provider,
        server_url=args.server_url,
        model=args.model or default_model
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
