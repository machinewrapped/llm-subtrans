import os
import logging

from check_imports import check_required_imports
check_required_imports(['PySubtrans', 'boto3'], 'bedrock')

from scripts.subtrans_common import (
    InitLogger,
    CreateArgParser,
    CreateOptions,
    CreateProject,
    TranslateProject,
)


provider = "Bedrock"

# Fetch Bedrock-specific environment variables
access_key = os.getenv('AWS_ACCESS_KEY_ID')
secret_access_key = os.getenv('AWS_SECRET_ACCESS_KEY')
aws_region = os.getenv('AWS_REGION', 'us-east-1')  # Default to a common Bedrock region

parser = CreateArgParser(f"Translates subtitles using a model on Amazon Bedrock")
parser.add_argument('-k', '--accesskey', type=str, default=None, help="AWS Access Key ID")
parser.add_argument('-s', '--secretkey', type=str, default=None, help="AWS Secret Access Key")
parser.add_argument('-r', '--region', type=str, default=None, help="AWS Region (default: us-east-1)")
parser.add_argument('-m', '--model', type=str, default=None, help="Model ID to use (e.g., amazon.titan-text-express-v1)")
args = parser.parse_args()

logger_options = InitLogger("bedrock-subtrans", args.debug)

try:
    options = CreateOptions(
        args,
        provider,
        access_key=args.accesskey or access_key,
        secret_access_key=args.secretkey or secret_access_key,
        aws_region=args.region or aws_region,
        model=args.model,
    )

    if not options.get('access_key') or not options.get('secret_access_key') or not options.get('aws_region') or not options.get('model'):
        raise ValueError("AWS Access Key, Secret Key, Region, and Model ID must be specified.")

    project = CreateProject(options, args)
    TranslateProject(project, options, verbose=args.verbose, preview=args.preview)

except Exception as e:
    logging.error(f"Error during subtitle translation: {e}")
    raise
