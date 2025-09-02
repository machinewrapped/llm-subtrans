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

provider = "Claude"
default_model = os.getenv('CLAUDE_MODEL') or "claude-3-haiku-20240307"

parser = CreateArgParser(f"Translates subtitles using Anthropic's Claude AI")
parser.add_argument('-k', '--apikey', type=str, default=None, help=f"Your Anthropic API Key (https://console.anthropic.com/settings/keys)")
parser.add_argument('-m', '--model', type=str, default=None, help="The model to use for translation")
parser.add_argument('--proxy', type=str, default=None, help="SOCKS proxy URL (e.g., socks://127.0.0.1:1089)")
args = parser.parse_args()

logger_options = InitLogger("claude-subtrans", args.debug)

try:
    options : Options = CreateOptions(args, provider, model=args.model or default_model, proxy=args.proxy)

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
