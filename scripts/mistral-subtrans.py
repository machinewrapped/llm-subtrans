import logging
import os

from check_imports import check_required_imports
check_required_imports(['PySubtrans', 'mistralai'], 'mistral')

from scripts.subtrans_common import (
    InitLogger,
    CreateArgParser,
    CreateOptions,
    CreateProject,
    TranslateProject,
)


from PySubtrans.Providers.Provider_Mistral import MistralProvider

provider = "Mistral"
default_model = os.getenv('MISTRAL_MODEL') or MistralProvider.default_model

parser = CreateArgParser(f"Translates subtitles using an Mistral model")
parser.add_argument('-k', '--apikey', type=str, default=None, help=f"Your Mistral API Key (https://console.mistral.ai/api-keys/)")
parser.add_argument('-m', '--model', type=str, default=None, help="The model to use for translation")
parser.add_argument('--server_url', type=str, default=None, help="Server URL (leave blank for default).")
args = parser.parse_args()

logger_options = InitLogger("mistral-subtrans", args.debug)

try:
    options = CreateOptions(
        args,
        provider,
        server_url=args.server_url,
        model=args.model or default_model
    )
    project = CreateProject(options, args)
    TranslateProject(project, options, verbose=args.verbose, preview=args.preview)

except Exception as e:
    logging.error(f"Error during subtitle translation: {e}")
    raise
