import logging
import os

from check_imports import check_required_imports
check_required_imports(['PySubtrans', 'google.genai', 'google.api_core'], 'gemini')

from scripts.subtrans_common import (
    InitLogger,
    CreateArgParser,
    CreateOptions,
    CreateProject,
    TranslateProject,
)

from PySubtrans.Providers.Provider_Gemini import GeminiProvider

provider = "Gemini"
default_model = os.getenv('GEMINI_MODEL') or GeminiProvider.default_model

parser = CreateArgParser(f"Translates subtitles using a Google Gemini model")
parser.add_argument('-k', '--apikey', type=str, default=None, help=f"Your Gemini API Key (https://makersuite.google.com/app/apikey)")
parser.add_argument('-m', '--model', type=str, default=None, help="The model to use for translation")
args = parser.parse_args()

logger_options = InitLogger("gemini-subtrans", args.debug)

try:
    options = CreateOptions(args, provider, model=args.model or default_model)
    project = CreateProject(options, args)
    TranslateProject(project, options, verbose=args.verbose, preview=args.preview)

except Exception as e:
    logging.error(f"Error during subtitle translation: {e}")
    raise
