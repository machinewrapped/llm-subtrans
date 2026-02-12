import os

from check_imports import check_required_imports
check_required_imports(['PySubtrans', 'google.genai', 'google.api_core'], 'gemini')

from scripts.subtrans_common import (
    InitLogger,
    CreateArgParser,
    CreateOptions,
    CreateProject,
    LogTranslationStatus,
)

from PySubtrans import init_translator
from PySubtrans.Options import Options
from PySubtrans.SubtitleProject import SubtitleProject
from PySubtrans.Providers.Provider_Gemini import GeminiProvider

provider = "Gemini"
default_model = os.getenv('GEMINI_MODEL') or GeminiProvider.default_model

parser = CreateArgParser(f"Translates subtitles using a Google Gemini model")
parser.add_argument('-k', '--apikey', type=str, default=None, help=f"Your Gemini API Key (https://makersuite.google.com/app/apikey)")
parser.add_argument('-m', '--model', type=str, default=None, help="The model to use for translation")
args = parser.parse_args()

logger_options = InitLogger("gemini-subtrans", args.debug)
project : SubtitleProject|None = None

try:
    options : Options = CreateOptions(args, provider, model=args.model or default_model)

    # Create a project for the translation
    project = CreateProject(options, args)

    # Translate the subtitles
    translator = init_translator(options)
    project.TranslateSubtitles(translator)

    if project.use_project_file:
        project.UpdateProjectFile()

    LogTranslationStatus(project, preview=args.preview)

except Exception as e:
    if project:
        LogTranslationStatus(project, preview=args.preview)
    print("Error:", e)
    raise
