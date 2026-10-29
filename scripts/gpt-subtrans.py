import logging
import os
import webbrowser

from check_imports import check_required_imports
check_required_imports(['PySubtrans', 'openai'], 'openai')

from scripts.subtrans_common import (
    InitLogger,
    CreateArgParser,
    CreateOptions,
    CreateProject,
    TranslateProject,
)


from PySubtrans.Auth.ChatGPTAuth import ChatGPTAuth
from PySubtrans.Providers.Provider_OpenAI import OpenAiProvider

provider = "OpenAI"
default_model = os.getenv('OPENAI_MODEL') or OpenAiProvider.default_model

parser = CreateArgParser(f"Translates subtitles using an OpenAI model")
parser.add_argument('-k', '--apikey', type=str, default=None, help=f"Your OpenAI API Key (https://platform.openai.com/account/api-keys)")
parser.add_argument('-b', '--apibase', type=str, default="https://api.openai.com/v1", help="API backend base address.")
parser.add_argument('-m', '--model', type=str, default=None, help="The model to use for translation")
parser.add_argument('--chatgpt', action='store_true', help="Sign in with ChatGPT and translate using your ChatGPT plan instead of an API key. Opens a browser to sign in if needed.")
parser.add_argument('--httpx', action='store_true', help="Use the httpx library for custom api_base requests. May help if you receive a 307 redirect error.")
args = parser.parse_args()

logger_options = InitLogger("gpt-subtrans", args.debug)

def OpenSignInPage(url : str) -> bool:
    """Open the sign-in page, showing the address in case no browser is available."""
    logging.info(f"Sign in with ChatGPT to continue. If your browser does not open, visit: {url}")
    return webbrowser.open(url)

try:
    if args.chatgpt:
        auth = ChatGPTAuth(proxy=getattr(args, 'proxy', None))
        if not auth.is_signed_in:
            auth.SignIn(open_browser=OpenSignInPage)
        logging.info(f"Using ChatGPT plan for {auth.account or 'the signed-in account'}")

    # Only override the setting when asked, so OPENAI_USE_CHATGPT_PLAN still applies
    auth_settings = { 'use_chatgpt_plan': True } if args.chatgpt else {}

    options = CreateOptions(
        args,
        provider,
        use_httpx=args.httpx,
        api_base=args.apibase,
        model=args.model or default_model,
        **auth_settings
    )
    project = CreateProject(options, args)
    TranslateProject(project, options, verbose=args.verbose, preview=args.preview)

except Exception as e:
    logging.error(f"Error during subtitle translation: {e}")
    raise
