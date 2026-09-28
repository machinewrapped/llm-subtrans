import logging
import os

from check_imports import check_required_imports
check_required_imports(['PySubtrans', 'anthropic'], 'claude')

from scripts.subtrans_common import (
    InitLogger,
    CreateArgParser,
    CreateOptions,
    CreateProject,
    TranslateProject,
)


from PySubtrans.Providers.Provider_Claude import ClaudeProvider

provider = "Claude"
default_model = os.getenv('CLAUDE_MODEL') or ClaudeProvider.default_model

parser = CreateArgParser(f"Translates subtitles using Anthropic's Claude AI")
parser.add_argument('-k', '--apikey', type=str, default=None, help=f"Your Anthropic API Key (https://console.anthropic.com/settings/keys)")
parser.add_argument('-m', '--model', type=str, default=None, help="The model to use for translation")
args = parser.parse_args()

logger_options = InitLogger("claude-subtrans", args.debug)

try:
    options = CreateOptions(args, provider, model=args.model or default_model)
    project = CreateProject(options, args)
    TranslateProject(project, options, verbose=args.verbose, preview=args.preview)

except Exception as e:
    logging.error(f"Error during subtitle translation: {e}")
    raise
