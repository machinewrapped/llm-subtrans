import os
import sys
import logging

# Add the parent directory to the sys path so that modules can be found
base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(base_path)

from scripts.subtrans_common import InitLogger, CreateArgParser, CreateOptions, CreateTranslator, CreateProject

from PySubtitle.Options import Options
from PySubtitle.SubtitleProject import SubtitleProject
from PySubtitle.SubtitleTranslator import SubtitleTranslator

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

    # Create a translator with the provided options
    translator : SubtitleTranslator = CreateTranslator(options)

    # Translate the subtitles
    project.TranslateSubtitles(translator)

    if project.write_project:
        logging.info(f"Writing project data to {str(project.projectfile)}")
        project.SaveProjectFile()

except Exception as e:
    print("Error:", e)
    raise
