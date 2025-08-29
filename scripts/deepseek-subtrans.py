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

provider = "DeepSeek"
default_model = os.getenv('DEEPSEEK_MODEL') or "deepseek-chat"

parser = CreateArgParser(f"Translates subtitles using an DeepSeek model")
parser.add_argument('-k', '--apikey', type=str, default=None, help=f"Your DeepSeek API Key (https://platform.deepseek.com/api_keys)")
parser.add_argument('-b', '--apibase', type=str, default="https://api.deepseek.com", help="API backend base address.")
parser.add_argument('-m', '--model', type=str, default=None, help="The model to use for translation")
args = parser.parse_args()

logger_options = InitLogger("deepseek-subtrans", args.debug)

try:
    options : Options = CreateOptions(
        args,
        provider,
        api_base=args.apibase,
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
