#!/bin/bash
#
# Install git hooks for llm-subtrans
# Run from project root: ./hooks/install.sh
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
HOOKS_DIR="$PROJECT_ROOT/.git/hooks"

if [ ! -d "$HOOKS_DIR" ]; then
    echo "Error: .git/hooks directory not found"
    echo "Make sure you're running this from the project root"
    exit 1
fi

echo "Installing git hooks..."

# Copy pre-commit hook
cp "$SCRIPT_DIR/pre-commit" "$HOOKS_DIR/pre-commit"
chmod +x "$HOOKS_DIR/pre-commit"

echo "Installed hooks:"
echo "  - pre-commit (runs pyright type checking)"
echo ""
echo "To skip the pre-commit hook, use: git commit --no-verify"
