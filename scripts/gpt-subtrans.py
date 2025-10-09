import os
import logging

from check_imports import check_required_imports
check_required_imports(['PySubtrans', 'openai'], 'openai')

from scripts.subtrans_common import (
    InitLogger,
    CreateArgParser,
    CreateOptions,
    CreateProject,
)

from PySubtrans import init_translator
from PySubtrans.Options import Options
from PySubtrans.SubtitleProject import SubtitleProject

# We'll write separate scripts for other providers
provider = "OpenAI"
default_model = os.getenv('OPENAI_MODEL') or "gpt-5-mini"

parser = CreateArgParser(f"Translates subtitles using an OpenAI model")
parser.add_argument('-k', '--apikey', type=str, default=None, help=f"Your OpenAI API Key (https://platform.openai.com/account/api-keys)")
parser.add_argument('-b', '--apibase', type=str, default="https://api.openai.com/v1", help="API backend base address.")
parser.add_argument('-m', '--model', type=str, default=None, help="The model to use for translation")
parser.add_argument('--httpx', action='store_true', help="Use the httpx library for custom api_base requests. May help if you receive a 307 redirect error.")
parser.add_argument('--proxy', type=str, default=None, help="SOCKS proxy URL (e.g., socks://127.0.0.1:1089)")
args = parser.parse_args()

logger_options = InitLogger("gpt-subtrans", args.debug)

try:
    options : Options = CreateOptions(
        args,
        provider,
        use_httpx=args.httpx,
        api_base=args.apibase,
        proxy=args.proxy,
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
