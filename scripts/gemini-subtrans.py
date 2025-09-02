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

provider = "Gemini"
default_model = os.getenv('GEMINI_MODEL') or "Gemini 2.0 Flash"

parser = CreateArgParser(f"Translates subtitles using a Google Gemini model")
parser.add_argument('-k', '--apikey', type=str, default=None, help=f"Your Gemini API Key (https://makersuite.google.com/app/apikey)")
parser.add_argument('-m', '--model', type=str, default=None, help="The model to use for translation")
args = parser.parse_args()

logger_options = InitLogger("gemini-subtrans", args.debug)

try:
    options : Options = CreateOptions(args, provider, model=args.model or default_model)

    # Create a project for the translation
    project : SubtitleProject = CreateProject(options, args)

    # Create a translator with the provided options
    translator : SubtitleTranslator = CreateTranslator(options)

    # Translate the subtitles
    project.TranslateSubtitles(translator)

    if project.use_project_file:
        logging.info(f"Writing project data to {str(project.projectfile)}")
        project.SaveProjectFile()

except Exception as e:
    print("Error:", e)
    raise
