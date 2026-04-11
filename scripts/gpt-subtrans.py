import logging
import os

from check_imports import check_required_imports
check_required_imports(['PySubtrans', 'openai'], 'openai')

from scripts.subtrans_common import (
    InitLogger,
    CreateArgParser,
    CreateOptions,
    CreateProject,
    TranslateProject,
)


from PySubtrans.Providers.Provider_OpenAI import OpenAiProvider

provider = "OpenAI"
default_model = os.getenv('OPENAI_MODEL') or OpenAiProvider.default_model

parser = CreateArgParser(f"Translates subtitles using an OpenAI model")
parser.add_argument('-k', '--apikey', type=str, default=None, help=f"Your OpenAI API Key (https://platform.openai.com/account/api-keys)")
parser.add_argument('-b', '--apibase', type=str, default="https://api.openai.com/v1", help="API backend base address.")
parser.add_argument('-m', '--model', type=str, default=None, help="The model to use for translation")
parser.add_argument('--httpx', action='store_true', help="Use the httpx library for custom api_base requests. May help if you receive a 307 redirect error.")
args = parser.parse_args()

logger_options = InitLogger("gpt-subtrans", args.debug)

try:
    options = CreateOptions(
        args,
        provider,
        use_httpx=args.httpx,
        api_base=args.apibase,
        model=args.model or default_model
    )
    project = CreateProject(options, args)
    TranslateProject(project, options, verbose=args.verbose, preview=args.preview)

except Exception as e:
    logging.error(f"Error during subtitle translation: {e}")
    raise
