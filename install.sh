#!/bin/bash
# Enable error handling
set -e

portable_install=false
config_path=""
if [ "$#" -gt 0 ]; then
    case "$1" in
        --portable)
            [ "$#" -eq 1 ] || { echo "Usage: ./install.sh [--portable | --configpath PATH]"; exit 1; }
            portable_install=true
            ;;
        --configpath)
            [ "$#" -eq 2 ] || { echo "Usage: ./install.sh [--portable | --configpath PATH]"; exit 1; }
            config_path=$2
            ;;
        *)
            echo "Usage: ./install.sh [--portable | --configpath PATH]"
            exit 1
            ;;
    esac
fi

if [ "$portable_install" = true ]; then
    echo
    echo "========================================"
    echo "Portable configuration mode enabled"
    echo "Settings and logs will be stored in .settings"
    echo "========================================"
elif [ -n "$config_path" ]; then
    echo
    echo "========================================"
    echo "Custom configuration mode enabled"
    echo "Settings and logs will be stored in: $config_path"
    echo "========================================"
fi

function set_env_var() {
    # Write NAME=value to .env, replacing any existing NAME entry
    local name=$1
    local value=$2

    if [ -f ".env" ]; then
        sed -i.bak "/^${name}=/d" .env
        rm -f .env.bak

        # Terminate an unterminated last line so the new entry is not merged into it
        if [ -n "$(tail -c 1 .env)" ]; then
            echo >> .env
        fi
    fi

    printf '%s=%s\n' "$name" "$value" >> .env
}

function install_provider() {
    local provider=$1
    local api_key_var_name=$2
    local extra_name=$3
    local script_name=$4
    local set_as_default=$5

    read -p "Enter your $provider API Key (optional): " api_key

    # Only update .env if user entered a new API key
    if [ -n "$api_key" ]; then
        set_env_var "${api_key_var_name}_API_KEY" "$api_key"
    fi

    # Set as default provider if requested
    if [ "$set_as_default" = "set_default" ]; then
        set_env_var PROVIDER "$provider"
    fi

    if [ -n "$extra_name" ]; then
        extras+=("$extra_name")
    fi
    scripts_to_generate+=("$script_name")
}

function install_bedrock() {
    echo "WARNING: Amazon Bedrock setup is not recommended for most users."
    echo "The setup requires AWS credentials, region configuration, and enabling specific model access in the AWS Console."
    echo "Proceed only if you are familiar with AWS configuration."
    echo

    read -p "Enter your AWS Access Key ID: " access_key
    read -p "Enter your AWS Secret Access Key: " secret_key
    read -p "Enter your AWS Region (e.g., us-east-1): " region

    set_env_var PROVIDER "Bedrock"
    set_env_var AWS_ACCESS_KEY_ID "$access_key"
    set_env_var AWS_SECRET_ACCESS_KEY "$secret_key"
    set_env_var AWS_REGION "$region"

    extras+=("bedrock")
    scripts_to_generate+=("bedrock-subtrans")

    echo "Bedrock setup complete. Default provider set to Bedrock."
}

function install_local_runtime() {
    # Install Torch and a local transcription runtime in its own environment, not in envsubtrans.
    # Usage: install_local_runtime runtime_name installer_script environment_folder provider_name
    local runtime_name="$1" installer="$2" environment="$3" provider_name="$4"

    echo
    if [ -d "$environment" ]; then
        echo "Updating the existing $runtime_name environment in \"$environment\"."
        echo "If $provider_name is not working, delete the \"$environment\" folder and run this installer again."
    else
        echo "Installing Torch and the $runtime_name runtime into \"$environment\"..."
    fi
    echo "Detecting GPU hardware and installing torch..."

    # CPU-only success returns 1, so capture it without triggering set -e.
    local runtime_exit=0
    ./envsubtrans/bin/python "scripts/$installer" "$environment" || runtime_exit=$?

    echo
    if [ $runtime_exit -eq 2 ]; then
        echo "Failed to install the $runtime_name runtime."
        echo "Skipping $provider_name; cloud transcription remains available."
    elif [ $runtime_exit -eq 1 ]; then
        echo "No GPU-accelerated torch variant was detected."
        echo "CPU inference is disabled by default. Enable allow_cpu_fallback in $provider_name advanced settings to consent to slow CPU inference."
        echo "For GPU acceleration, install the hardware-appropriate PyTorch build from:"
        echo "  https://pytorch.org/get-started/locally/"
    else
        echo "$provider_name installed successfully with GPU support."
    fi
    echo
}

if [ ! -d "scripts" ]; then
    echo "Please run the script from the root directory of the project."
    exit 1
fi

echo "Checking if Python 3 is installed..."
if ! python3 --version &>/dev/null; then
    echo "Python 3 not found. Please install Python 3 and try again."
    exit 1
fi

PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
MIN_VERSION="3.10.0"

if [[ "$(printf '%s\n' "$MIN_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$MIN_VERSION" ]]; then
    echo "Detected Python version is less than 3.10.0. Please upgrade your Python version."
    exit 1
else
    echo "Python version is compatible."
fi

echo "Checking if \"envsubtrans\" folder exists..."
if [ -d "envsubtrans" ]; then
    echo "\"envsubtrans\" folder already exists."
    read -p "Do you want to perform a clean install? This will delete the existing environment. (Y/N): " user_choice
    if [ "$user_choice" = "Y" ] || [ "$user_choice" = "y" ]; then
        echo "Performing a clean install..."
        rm -rf envsubtrans
        [ -f .env ] && rm .env
    elif [ "$user_choice" != "N" ] && [ "$user_choice" != "n" ]; then
        echo "Invalid choice. Exiting installation."
        exit 1
    fi
fi

extras=()
scripts_to_generate=("llm-subtrans" "batch-translate" "transcribe")

echo "Select installation type:"
echo "1 = Install with GUI"
echo "2 = Install command line tools only"
read -p "Enter your choice (1/2): " install_choice

if [ "$install_choice" = "2" ]; then
    echo "Installing command line modules..."
else
    echo "Including GUI modules..."
    extras+=("gui")
    scripts_to_generate+=("gui-subtrans")
fi

if [ -n "$config_path" ]; then
    mkdir -p "$config_path"
elif [ "$portable_install" = true ]; then
    mkdir -p .settings
fi

if [ "$portable_install" = true ] && [ -f ".env" ]; then
    sed -i.bak '/^LLM_SUBTRANS_CONFIG_PATH=/d' .env
    rm -f .env.bak
fi

if [ -n "$config_path" ]; then
    set_env_var LLM_SUBTRANS_CONFIG_PATH "$config_path"
fi

# Optional: configure OpenRouter API key
echo "Optional: Configure OpenRouter API key (default provider)"
read -p "Enter your OpenRouter API Key (optional): " openrouter_key
if [ -n "$openrouter_key" ]; then
    set_env_var OPENROUTER_API_KEY "$openrouter_key"
fi

echo "Select additional providers to install:"
echo "0 = None"
echo "1 = OpenAI"
echo "2 = Google Gemini"
echo "3 = Anthropic Claude"
echo "4 = DeepSeek"
echo "5 = Mistral"
echo "6 = Bedrock (AWS)"
echo "a = All except Bedrock"
read -p "Enter your choice (0/1/2/3/4/5/6/a): " provider_choice

case $provider_choice in
    0)
        echo "No additional provider selected."
        ;;
    1)
        install_provider "OpenAI" "OPENAI" "openai" "gpt-subtrans" "set_default"
        ;;
    2)
        install_provider "Google Gemini" "GEMINI" "gemini" "gemini-subtrans" "set_default"
        ;;
    3)
        install_provider "Claude" "CLAUDE" "claude" "claude-subtrans" "set_default"
        ;;
    4)
        install_provider "DeepSeek" "DEEPSEEK" "" "deepseek-subtrans" "set_default"
        ;;
    5)
        install_provider "Mistral" "MISTRAL" "mistral" "mistral-subtrans" "set_default"
        ;;
    6)
        install_bedrock
        ;;
    a)
        install_provider "Google Gemini" "GEMINI" "gemini" "gemini-subtrans" ""
        install_provider "OpenAI" "OPENAI" "openai" "gpt-subtrans" ""
        install_provider "Claude" "CLAUDE" "claude" "claude-subtrans" ""
        install_provider "DeepSeek" "DEEPSEEK" "" "deepseek-subtrans" ""
        install_provider "Mistral" "MISTRAL" "mistral" "mistral-subtrans" ""
        ;;
    *)
        echo "Invalid choice. Exiting installation."
        exit 1
        ;;
esac

echo
while true; do
    read -p "Install local transcription? (y/n): " install_transcription

    case $install_transcription in
        y|Y|n|N)
            break
            ;;
        *)
            echo "Please enter y or n."
            ;;
    esac
done

install_qwen=""
install_moss=""
if [ "$install_transcription" = "y" ] || [ "$install_transcription" = "Y" ]; then
    echo
    echo "Local transcription runtimes, each installed in its own environment:"
    echo "1 = Qwen Local: Qwen3-ASR with word timings"
    echo "2 = MOSS Local: MOSS-Transcribe-Diarize with speaker labels"
    echo "3 = Both"
    while true; do
        read -p "Enter your choice (1/2/3): " runtime_choice

        case $runtime_choice in
            1) install_qwen=1; break ;;
            2) install_moss=1; break ;;
            3) install_qwen=1; install_moss=1; break ;;
            *) echo "Please enter 1, 2 or 3." ;;
        esac
    done
else
    echo "No local transcription selected."
fi

if [ ! -d "envsubtrans" ]; then
    echo
    echo "Creating virtual environment..."
    python3 -m venv --upgrade-deps envsubtrans
fi

source envsubtrans/bin/activate

install_target="."
if [ ${#extras[@]} -gt 0 ]; then
    IFS=','; extra_str="${extras[*]}"; unset IFS
    echo "Installing dependencies: $extra_str"
    install_target=".[${extra_str}]"
else
    echo "Installing dependencies..."
fi

# Skip releases less than 7 days old, so a malicious release is likely to be pulled before it is installed.
# Needs a recent pip, so upgrade pip first.
upload_cooldown="--uploaded-prior-to=P7D"
pip install --upgrade pip
pip install --upgrade "$upload_cooldown" -e "$install_target"

# Qt no longer ships bundled fonts; create the expected directory so Qt's font
# discovery does not emit a warning when running headless (offscreen) tests.
qt_fonts_dir=$(python3 -c "import PySide6, os; print(os.path.join(os.path.dirname(PySide6.__file__), 'lib', 'fonts'))" 2>/dev/null || true)
[ -n "$qt_fonts_dir" ] && mkdir -p "$qt_fonts_dir"

if [ -n "$install_qwen" ]; then
    install_local_runtime "Qwen" install_qwen_runtime.py envqwen "Qwen Local"
fi
if [ -n "$install_moss" ]; then
    install_local_runtime "MOSS" install_moss_runtime.py envmoss "MOSS Local"
fi

for script in "${scripts_to_generate[@]}"; do
    scripts/generate-cmd.sh "$script"
done

echo "Setup completed successfully. To uninstall just delete the directory"

exit 0
