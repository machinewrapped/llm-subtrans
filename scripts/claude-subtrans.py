import logging
import os

from check_imports import check_required_imports
check_required_imports(['PySubtrans', 'anthropic'], 'claude')

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
from PySubtrans.Providers.Provider_Claude import ClaudeProvider

provider = "Claude"
default_model = os.getenv('CLAUDE_MODEL') or ClaudeProvider.default_model

parser = CreateArgParser(f"Translates subtitles using Anthropic's Claude AI")
parser.add_argument('-k', '--apikey', type=str, default=None, help=f"Your Anthropic API Key (https://console.anthropic.com/settings/keys)")
parser.add_argument('-m', '--model', type=str, default=None, help="The model to use for translation")
args = parser.parse_args()

logger_options = InitLogger("claude-subtrans", args.debug)
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
        LogTranslationStatus(project, preview=args.preview, has_error=True)
    logging.error(f"Error during subtitle translation: {e}")
    raise
