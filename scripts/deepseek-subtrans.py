import logging
import os

from check_imports import check_required_imports
check_required_imports(['PySubtrans'])

from scripts.subtrans_common import (
    InitLogger,
    CreateArgParser,
    CreateOptions,
    CreateProject,
    TranslateProject,
)


from PySubtrans.Providers.Provider_DeepSeek import DeepSeekProvider

provider = "DeepSeek"
default_model = os.getenv('DEEPSEEK_MODEL') or DeepSeekProvider.default_model

parser = CreateArgParser(f"Translates subtitles using an DeepSeek model")
parser.add_argument('-k', '--apikey', type=str, default=None, help=f"Your DeepSeek API Key (https://platform.deepseek.com/api_keys)")
parser.add_argument('-b', '--apibase', type=str, default="https://api.deepseek.com", help="API backend base address.")
parser.add_argument('-m', '--model', type=str, default=None, help="The model to use for translation")
args = parser.parse_args()

logger_options = InitLogger("deepseek-subtrans", args.debug)

try:
    options = CreateOptions(
        args,
        provider,
        api_base=args.apibase,
        model=args.model or default_model
    )
    project = CreateProject(options, args)
    TranslateProject(project, options, verbose=args.verbose, preview=args.preview)

except Exception as e:
    logging.error(f"Error during subtitle translation: {e}")
    raise
