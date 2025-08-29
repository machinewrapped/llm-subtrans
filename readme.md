# LLM-Subtrans
LLM-Subtrans is an open source subtitle translator that uses LLMs as a translation service. It can translate subtitles between any language pairs supported by the language model.

Note: LLM-Subtrans requires an active internet connection. Subtitles are sent to the provider's servers for translation, so their privacy policy applies.

## Installation
For most users the packaged release is the easiest way to use the program. Download a package from [the releases page](https://github.com/machinewrapped/llm-subtrans/releases), unzip to a folder and run `gui-subtrans`. You will be prompted for some basic settings on first run.

### Windows
Every release is packaged for Windows as (**gui-subtrans-x.x.x.zip**).

### MacOS
Packaged builds are usually provided for MacOS with Apple Silicon (**gui-subtrans-x.x.x.macos-arm64.zip**). If the latest release does not have a macos-arm64 package you can download an earlier release or [install from source](#installing-from-source).

If you have an Intel Mac you will need to install from source. If anybody would like to volunteer to maintain Intel releases, please get in touch.

### Linux
Prebuilt Linux packages are not provided so you will need to install from source.

## Translation Providers

### OpenRouter
https://openrouter.ai/privacy

[OpenRouter](https://openrouter.ai/) is a service which aggregates [models](https://openrouter.ai/models) from a wide range of providers. You will need an [OpenRouter API Key](https://openrouter.ai/settings/keys) to use the service, and a credit balance (though some quite capable models are provided free of charge).

You can choose to let OpenRouter select the model automatically (the "Use Default Model" setting in the GUI or `--auto` on the command line) or you can specify a specific model. Model preferences can also be specified in the OpenRouter dashboard.

Since hundreds of models are available they are grouped by model family. By default the list of available models is pulled from the "Translation" category - though this excludes many other models that are perfectly capable of translation.

### OpenAI
https://openai.com/policies/privacy-policy

You will need an OpenAI API key from https://platform.openai.com/account/api-keys to use OpenAI's GPT models as a translator.

If the API key is associated with a free trial account the translation speed will be severely restricted.

You can use the custom api_base parameter to access a custom OpenAI instance or other providers with an OpenAI compatible API (which is most of them).

You can use an **OpenAI Azure** installation as a translation provider, but this is only advisable if you know what you're doing - in which case hopefully it will be clear how to configure the Azure provider settings.

### Google Gemini
https://ai.google.dev/terms

**Please note that regions restrictions may apply: https://ai.google.dev/available_regions**

You will need a Google Gemini API key from https://ai.google.dev/ or from a project created on https://console.cloud.google.com/. You must ensure that Generative AI is enabled for the api key and project.

The Gemini 2.0 Flash Experimental model is perhaps the leading model for translation speed and fluency at time of writing, and is currently free to use.

### Anthropic Claude
https://support.anthropic.com/en/collections/4078534-privacy-legal

You will need an Anthropic API key from https://console.anthropic.com/settings/keys to use Claude as a provider. The Anthropic SDK does not provide a way to retrieve available models, so the latest Claude 3 model names are currently hardcoded.

The API has very strict [rate limits](https://docs.anthropic.com/claude/reference/rate-limits) based on your credit tier, both on requests per minutes and tokens per day. The free credit tier should be sufficient to translate approximately one full movie per day.

### DeepSeek
https://platform.deepseek.com/downloads/DeepSeek%20Open%20Platform%20Terms%20of%20Service.html

You will need a DeepSeek API key from https://platform.deepseek.com/api_keys to use this provider.

- **API Base**: You can optionally specify a custom URL, e.g. if you are hosting your own DeepSeek instance. If this is not set, the official DeepSeek API endpoint will be used.

- **Model**: The default model is `deepseek-chat`, which is recommended for translation tasks. `deepseek-reasoner` may produce better results for source subtitles with OCR or transcription errors as it will spend longer trying to guess what the error is.

DeepSeek is quite simple to set up and offers reasonable performance at a very low price, though translation does not seem to be its strongest point.

### Mistral AI
https://mistral.ai/terms/

You will need a Mistral API key from https://console.mistral.ai/api-keys/ to use this provider.

- **Server URL**: If you are using a custom deployment of the Mistral API, you can specify the server URL using the `--server_url` argument.

- **Model**: `mistral-large-latest` is recommended for translation. Smaller models tend to perform poorly and may not follow the system instructions well.

Mistral AI is straightforward to set up, but its performance as a translator is not particularly good.

### Custom Server
LLM-Subtrans can interface directly with any server that supports an OpenAI compatible API, including locally hosted models e.g. [LM Studio](https://lmstudio.ai/).

This is mainly for research and you should not expect particularly good results. LLMs derive much of their power from their size, so the small, quantized models you can run on a GPU are likely to produce poor translations, fail to generate valid responses or get stuck in endless loops. If you find a model that reliably producess good results, please post about it in the Discussions area!

Chat and completion endpoints are supported, you should configure the settings and endpoint based on the model the server is running (e.g. instruction tuned models will probably produce better results using the completions endpoint rather than chat/conversation). The prompt template can be edited in the GUI if you are using a model that requires a particular format - make sure to include at least the {prompt} tag in the template, as this is where the subtitles that need translating in each batch will be provided.

### Amazon Bedrock
https://aws.amazon.com/service-terms/

**Bedrock is not recommended for most users**: The setup process is complex, requiring AWS credentials, proper IAM permissions, and region configuration. Additionally, not all models on Bedrock support translation tasks or offer reliable results. Bedrock support will not be included in pre-packaged versions - if you can handle setting up AWS, you can handle installing llm-subtrans from source!

To use Bedrock, you must:
  1. Create an **IAM user** or **role** with appropriate permissions (e.g., `bedrock:InvokeModel`, `bedrock:ListFoundationModels`).
  2. Ensure the model you wish to use is accessible in your selected AWS region and [enabled for the IAM user](https://docs.aws.amazon.com/bedrock/latest/userguide/model-access-modify.html).

## Installing from source
For other platforms, or if you want to modify the program, you will need to have Python 3.10+ and pip installed on your system, then follow these steps.

1. Clone the LLM-Subtrans repository onto your local machine using the following command:

    ```sh
    git clone https://github.com/machinewrapped/llm-subtrans.git
    ```

### Installation scripts

The easiest setup method is to run the unified installation script:
- **Windows**: Run `install.bat`
- **MacOS/Linux**: Run `install.sh`

These scripts will create a virtual environment and guide you through selecting and installing your preferred provider(s). They will also generate appropriate command scripts to launch the applications.

During the installing process, you can choose to input an API key for each selected provider when prompted. It will be saved in a .env file so that you don't need to provide it every time you run the program.

#### Manual configuration
**If you ran an install script you can skip the remaining steps. Continue reading _only_ if you want to configure the environment manually instead.**

2. Create a new file named .env in the root directory of the project. Add any required settings for your chosen provider to the .env file like this:
    ```sh
    OPENROUTER_API_KEY=<your_openrouter_api_key>
    OPENAI_API_KEY=<your_openai_api_key>
    GEMINI_API_KEY=<your_gemini_api_key>
    AZURE_API_KEY=<your_azure_api_key>
    CLAUDE_API_KEY=<your_claude_api_key>
    ```

    If you are using Azure:

    ```sh
    AZURE_API_BASE=<your api_base, such as https://something.openai.azure.com>
    AZURE_DEPLOYMENT_NAME=<deployment_name>
    ```

    If you are using Bedrock:
    ```sh
    AWS_ACCESS_KEY_ID=your-access-key-id
    AWS_SECRET_ACCESS_KEY=your-secret-access-key
    AWS_REGION=your-region
    ```

    For OpenAI reasoning models you can set the reasoning effort (default is low):
    ```sh
    OPENAI_REASONING_EFFORT=low/medium/high
    ```

3. Create a virtual environment for the project by running the following command in the root folder to create a local environment for the Python interpreter.:

    ```sh
    python -m venv envsubtrans
    ```

4. Activate the virtual environment by running the appropriate command for your operating system:

    ```sh
    .\envsubtrans\Scripts\activate      # Windows
    source ./envsubtrans/bin/activate   # Mac/Linux
    ```

5. Install the required libraries using pip by running the following command in your terminal to install the project dependencies (listed in the requirements.txt file):

    ```sh
    pip install -r requirements.txt
    ```

6. Install any additional SDKs required for the provider(s) you intend to use:

    ```sh
    pip install openai
    pip install google-genai google-api-core
    pip install anthropic
    pip install mistral
    ```

Note that steps 3 and 4 are optional but recommended, as they help prevent conflicts with other Python applications.

## Usage
The program works by dividing the subtitles up into small batches and sending each one to the translation service in turn. It is likely to take time to complete, and can potentially make many API calls for each subtitle file.

By default The translated subtitles will be written to a new file in the same directory with the target langugage appended to the original filename.

Subtitle Edit's (https://www.nikse.dk/subtitleedit) "Fix Common Errors" can help to clean up the translated subtitles, though some of its functionality is now covered by the post-process option (`--postprocess`) in LLM-Subtrans.

### GUI
The [Subtrans GUI](https://github.com/machinewrapped/llm-subtrans/wiki/GUI#gui-subtrans) is the best and easiest way to use the program. After installation, launch the GUI with the `gui-subtrans` command or shell script, and hopefully the rest should be self-explanatory.

See the project wiki for further details on how to use the program.

### Command Line

LLM-Subtrans can be used as a console command or shell script. The install scripts create a cmd or sh file in the project root for each provider, which will take care of activating the virtual environment and calling the corresponding translation script.

The most basic usage is:
```sh
# Use OpenRouter with automatic model selection
llm-subtrans --auto -l <language> <path_to_srt_file>

# Use OpenRouter with a specific model
llm-subtrans --model google/gemini-2.5-flash -l <language> <path_to_srt_file>

# Use any server with an OpenAI-compatible API
llm-subtrans -s <server_address> -e <endpoint> -k <api_key> -l <language> <path_to_srt_file>

# Use specific providers
gpt-subtrans <path_to_srt_file> --target_language <target_language>
gemini-subtrans <path_to_srt_file> --target_language <target_language>
claude-subtrans <path_to_srt_file> --target_language <target_language>

# process files in different folders (the script will need editing to configure the path and provider settings)
python3 batch_process.py
```

If the target language is not specified the default is English.

Other options that can be specified on the command line are detailed below.

## Project File

**Note** If you are using the GUI a project file is created automatically when you open a subtitle file for the first time, and updated automatically.

The `--project` argument or `PROJECT` .env setting can take a number of values, which control whether and when an intermediate file will be written to disc.

The default setting is `None`, which means the project file is neither written nor read, the only output of the program is the final translation.

If the argument is set to `True` then a project file will be created with the `.subtrans` extension, containing details of the translation process,
and it will be updated as the translation progresses. Writing a project file allows, amongst other things, resuming a translation that was interrupted.

Other valid options include `preview`, `resume`, `reparse` and `retranslate`. These are probably only useful if you're modifying the code, in which case
you should be able to see what they do.

## Advanced usage

There are a number of command-line arguments that offer more control over the translation process.

To use any of these arguments, add them to the command-line after the path to the source file. For example:

```sh
llm-subtrans path/to/my/subtitles.srt --moviename "My Awesome Movie" --ratelimit 10 --substitution cat::dog
```

Default values for many settings can be set in the .env file, using a NAME_IN_CAPS format. See Options.py and the various Provider_XXX files for the full list.

- `-l`, `--target_language`:
  The language to translate the subtitles to.

- `-o`, `--output`:
  Specify a filename for the translated subtitles.

- `--project`:
  Read or Write a project file for the subtitles being translated (see above for details)

- `--ratelimit`:
  Maximum number of requests to the translation service per minute (mainly relevant if you are using an OpenAI free trial account).

- `--moviename`:
  Optionally identify the source material to give context to the translator.

- `--description`:
  A brief description of the source material to give further context. Less is generally more here, or the AI can start improvising.

- `--name`, `--names`:
  Optionally provide (a list of) names to use in the translation (more powerful AI models are more likely to actually use them).

- `--substitution`:
  A pair of strings separated by `::`, to substitute in either source or translation, or the name of a file containing a list of such pairs.

- `--scenethreshold`:
  Number of seconds between lines to consider it a new scene.

- `--minbatchsize`:
  Minimum number of lines to consider starting a new batch to send to the translator.
  Higher values typically result in faster and cheaper translations but increase the risk of desyncs.

- `--maxbatchsize`:
  Maximum number of lines before starting a new batch is compulsory.
  This needs to take into account the token limit for the model being used, but the "optimal" value depends on many factors, so experimentation is encouraged.
  Larger batches are more cost-effective but increase the risk of the AI desynchronising, triggering expensive retries.

- `--preprocess`:
  Preprocess the subtitles prior to batching.
  This performs various actions to prepare the subtitles for more efficient translation, e.g. splitting long (duration) lines into multiple lines.
  Mainly intended for subtitles that have been automatically transcribed with e.g. Whisper.

- `--postprocess`:
  Post-process translated subtitles.
  Performs various actions like adding line breaks to long lines and normalising dialogue tags after a translation request.

- `--instruction`:
  An additional instruction for the AI indicating how it should approach the translation.

- `--instructionfile`:
  Name/path of a file to load AI system instructions from (otherwise the default instructions.txt is used).

- `--maxlines`:
  Maximum number of batches to process. To end the translation after a certain number of lines, e.g. to check the results.

- `--temperature`:
  A higher temperature increases the random variance of translations. Default 0.

### Provider-specific arguments
Some additional arguments are available for specific providers.

#### OpenRouter
- `-k`, `--apikey`:
  Your [OpenRouter API Key](https://openrouter.ai/settings/keys) (the app will look for OPENROUTER_API_KEY in the environment if this is not provided)

- `--auto`
  Automatically select the model to use (selection criteria can be configured in the [OpenRouter Dashboard](https://openrouter.ai/settings/preferences))

#### OpenAI
- `-k`, `--apikey`:
  Your [OpenAI API Key](https://platform.openai.com/account/api-keys).

- `-b`, `--apibase`:
  API base URL if you are using a custom instance. if it is not set, the default URL will be used.

- `-httpx`:
  Use the [HTTPX library](https://github.com/projectdiscovery/httpx) for requests (only supported if apibase is specified)

- `-m`, `--model`:
  Specify the [AI model](https://platform.openai.com/docs/models) to use for translation

- `--proxy`:
  SOCKS proxy URL

#### Gemini
- `-k`, `--apikey`:
  Your [Google Gemini API Key](https://aistudio.google.com/app/apikey). Not required if it is set in the .env file.

- `-m`, `--model`:
  Specify the [AI model](https://ai.google.dev/models/gemini) to use for translation

#### Claude
- `-k`, `--apikey`:
  Your [Anthropic API Key](https://console.anthropic.com/settings/keys). Not required if it is set in the .env file.

- `-m`, `--model`:
  Specify the [AI model](https://docs.anthropic.com/claude/docs/models-overview#model-comparison) to use for translation. This should be the full model name, e.g. `claude-3-haiku-20240307`

#### OpenAI Azure
- `--deploymentname`:
  Azure deployment name

- `-k`, `--apikey`:
  API key [for your deployment](https://learn.microsoft.com/en-us/azure/ai-services/openai/).

- `-b`, `--apibase`:
  API backend base address.

- `-a`, `--apiversion`:
  Azure API version.

#### DeepSeek
  - `-k`, `--apikey`:
  Your [DeepSeek API Key](https://platform.deepseek.com/api_keys).

- `-b`, `--apibase`:
  Base URL if you are using a custom deployment of DeepSeek. if it is not set, the official URL will be used.

- `-m`, `--model`:
  Specify the [model](https://api-docs.deepseek.com/quick_start/pricing) to use for translation. **deepseek-chat** is probably the only sensible choice (and default).

#### Mistral AI
  - `-k`, `--apikey`:
  Your [DeepSeek API Key](https://console.mistral.ai/api-keys/).

- `--server_url`:
  URL if you are using a custom deployment of Mistral. if unset, the official URL will be used.

- `-m`, `--model`:
  Specify the [model](https://docs.mistral.ai/getting-started/models/models_overview/) to use for translation. **mistral-large-latest** is recommended, the small models are not very reliable.

#### Amazon Bedrock
- `-k`, `--accesskey`:
  Your [AWS Access Key ID](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_access-keys.html). Not required if it is set in the `.env` file.

- `-s`, `--secretkey`:
  Your [AWS Secret Access Key](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_access-keys.html). Not required if it is set in the `.env` file.

- `-r`, `--region`:
  AWS Region where Bedrock is available. You can check the list of regions [here](https://aws.amazon.com/about-aws/global-infrastructure/regions_az/). For example: `us-east-1` or `eu-west-1`.

- `-m`, `--model`:
  The ID of the [Bedrock model](https://docs.aws.amazon.com/bedrock/latest/userguide/foundation-models.html) to use for translation. Examples include `amazon.titan-text-lite-v1` or `amazon.titan-text-express-v1`.

#### Custom Server specific arguments
- `-s`, `--server`:
  The address the server is running on, including port (e.g. http://localhost:1234). Should be provided by the server

- `-e`, `--endpoint`:
  The API function to call on the server, e.g. `/v1/completions`. Choose an appropriate endpoint for the model running on the server.

- `-k`, `--apikey`:
  API key if required (local servers shouldn't need an api key)

- `-m`, `--model`:
  The model to use for translation if required (for local servers this is probably determined by the server)

- `--chat`:
  Specify this argument if the endpoint expects requests in a conversation format - otherwise it is assumed to be a completion endpoint.

- `--systemmessages`:
  If using a conversation endpoint, translation instructions will be sent as the "system" user if this flag is specified.


### Proxy

If you need to use proxy in your location, you can use socks proxy by using command line

```sh
python3 gpt-subtrans.py <path_to_srt_file> --target_language <target_language> --proxy socks://127.0.0.1:1089
```
Remember to change the local port to yours and turn on your proxy tools such as v2ray, naiveproxy and clash.

### batch process

you can process files with the following struct：

      #   -SRT
      #   --fold1
      #   ---1.srt
      #   ---2.srt
      #   ...
      #   --fold2
      #   ---1.srt
      #   ---2.srt
      #   ...

```sh
python3 batch_process.py  # process files in different folders
```
You need to modify the command line in batch_process.py accordingly.

### Developers
It is recommended to use an IDE such as Visual Studio Code to run the program when installed from source, and set up a launch.json file to specify the arguments.

Note: Remember to activate the virtual environment every time you work on the project.

## Contributing
Contributions from the community are welcome! To contribute, follow these steps:

Fork the repository onto your own GitHub account.

Clone the repository onto your local machine using the following command:

```sh
git clone https://github.com/your_username/llm-subtrans.git
```

Create a new branch for your changes using the following command:

```sh
git checkout -b feature/your-new-feature
```

Make your changes to the code and commit them with a descriptive commit message.

Push your changes to your forked repository.

Submit a pull request to the main LLM-Subtrans repository.

### Localization

LLM-Subtrans uses GNU gettext for UI localization.

- Template (POT): `locales/gui-subtrans.pot`
- Per‑language catalogs: `locales/<lang>/LC_MESSAGES/gui-subtrans.po`
- Compiled catalogs: `locales/<lang>/LC_MESSAGES/gui-subtrans.mo`

Strings in the code are marked with helpers (see codebase):
- `_("text")` for simple strings
- `tr("context", "text")` for contextualized strings

Contributions are very welcome - you can add a new localization in minutes! See `docs/localization_contributing.md` for detailed instructions (tools, workflow, etc).

## Acknowledgements
This project uses several useful libraries:

- srt (https://github.com/cdown/srt)
- requests (https://github.com/psf/requests)
- regex (https://github.com/mrabarnett/mrab-regex)
- httpx (https://github.com/projectdiscovery/httpx)
- babel (https://github.com/python-babel/)

Translation providers:
- openai (https://platform.openai.com/docs/libraries/python-bindings)
- google-genai (https://github.com/googleapis/python-genai)
- anthropic (https://github.com/anthropics/anthropic-sdk-python)
- mistralai (https://github.com/mistralai/client-python)
- boto3 (Amazon Bedrock) (https://github.com/boto/boto3)

For the GUI:
- pyside6 (https://wiki.qt.io/Qt_for_Python)
- events (https://pypi.org/project/Events/)
- darkdetect (https://github.com/albertosottile/darkdetect)
- appdirs (https://github.com/ActiveState/appdirs)

For bundled versions:
- python (https://www.python.org/)
- pyinstaller (https://pyinstaller.org/)

## Version History

Version 1.3 added OpenRouter as the default translation service, opening up access to many more

Version 1.2 added localization for the GUI and support for the GPT-5 model line.

Version 1.1 added support for a more flexible translation format for use with custom instructions.

Version 1.0 is (ironically) a minor update, updating the major version to 1.0 because the project has been stable for some time.

Version 0.7 introduced optional post-processing of translated subtitles to try to fix some of the common issues with LLM-translated subtitles (e.g. adding line breaks), along with new default instructions that tend to produce fewer errors.

Version 0.6 changes the architecture to a provider-based system, allowing multiple AI services to be used as translators.
Settings are compartmentalised for each provider. For the intial release the only supported provider is **OpenAI**.

Version 0.5 adds support for gpt-instruct models and a refactored code base to support different translation engines. For most users, the recommendation is still to use the **gpt-3.5-turbo-16k** model with batch sizes of between (10,100) lines, for the best combination of performance/cost and translation quality.

Version 0.4 features significant optimisations to the GUI making it more responsive and usable, along with numerous bug fixes.

Version 0.3 featured a major effort to bring the GUI up to full functionality and usability, including adding options dialogs and more, plus many bug fixes.

Version 0.2 employs a new prompting approach that greatly reduces desyncs caused by GPT merging together source lines in the translation. This can reduce the naturalness of the translation when the source and target languages have very different grammar, but it provides a better base for a human to polish the output.

The instructions have also been made more detailed, with multiple examples of correct output for GPT to reference, and the generation of summaries has been improved so that GPT is better able to understand the context of the batch it is translating. Additionally, double-clicking a scene or batch now allows the summary to be edited by hand, which can greatly improve the results of a retranslation and of subsequent batches or scenes. Individually lines can also be edited by double-clicking them.

## License
LLM-Subtrans is licensed under the MIT License. See LICENSE for the 3rd party library licenses.
