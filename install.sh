#!/usr/bin/env bash
# Installs the Ustad Hotel voice agent on macOS or Ubuntu with one command:
#
#   curl -fsSL https://raw.githubusercontent.com/dev3-trojanitsolutions/voice-sandwich-demo/main/install.sh | bash
#
# Options (after "bash -s --" when piped):
#   --no-llm     don't install Ollama and the local model (about 4 GB)
#   --no-voice   don't install the local voice service (Apple silicon only)
#
# Environment: INSTALL_DIR (default ./voice-sandwich-demo), REPO_URL, BRANCH.
# Windows: use install.ps1.

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/dev3-trojanitsolutions/voice-sandwich-demo.git}"
BRANCH="${BRANCH:-main}"
INSTALL_DIR="${INSTALL_DIR:-$PWD/voice-sandwich-demo}"
WITH_LLM=1
WITH_VOICE=1

for arg in "$@"; do
  case "$arg" in
    --no-llm) WITH_LLM=0 ;;
    --no-voice) WITH_VOICE=0 ;;
    *) echo "Unknown option: $arg" >&2; exit 1 ;;
  esac
done

step() { printf '\n==> %s\n' "$*"; }
fail() { printf '\nError: %s\n' "$*" >&2; exit 1; }
has() { command -v "$1" >/dev/null 2>&1; }

OS="$(uname -s)"
case "$OS" in
  Darwin | Linux) ;;
  *) fail "Use install.ps1 on Windows. This script is for macOS and Ubuntu." ;;
esac

sudo_cmd() {
  if [ "$(id -u)" -eq 0 ]; then "$@"; else sudo "$@"; fi
}

step "Checking system tools"
if [ "$OS" = Linux ]; then
  has apt-get || fail "This script supports Ubuntu/Debian (apt-get). Install git, make, curl, Node.js 18+, uv and pnpm, then run 'make install-all'."
  missing=()
  for tool in git make curl lsof; do has "$tool" || missing+=("$tool"); done
  has zstd || missing+=(zstd) # the Ollama installer needs it
  if [ ${#missing[@]} -gt 0 ]; then
    sudo_cmd apt-get update
    sudo_cmd apt-get install -y "${missing[@]}" ca-certificates
  fi
else
  has git && has make || fail "Install the Xcode command line tools first: xcode-select --install"
fi

node_major() { node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0; }
if ! has node || [ "$(node_major)" -lt 18 ]; then
  step "Installing Node.js (LTS)"
  if [ "$OS" = Linux ]; then
    curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo_cmd bash -
    sudo_cmd apt-get install -y nodejs
  elif has brew; then
    brew install node
  else
    fail "Install Node.js 18 or newer from https://nodejs.org (or install Homebrew), then run this script again."
  fi
fi

if ! has uv; then
  step "Installing uv (Python package manager)"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

if ! has pnpm; then
  step "Installing pnpm"
  corepack enable pnpm 2>/dev/null || sudo_cmd corepack enable pnpm 2>/dev/null \
    || npm install -g pnpm 2>/dev/null || sudo_cmd npm install -g pnpm
fi

step "Downloading the application to $INSTALL_DIR"
if [ -d "$INSTALL_DIR/.git" ]; then
  git -C "$INSTALL_DIR" pull --ff-only
else
  git clone --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
fi

step "Installing packages and building the web pages"
if [ "$WITH_VOICE" = 1 ]; then
  make -C "$INSTALL_DIR" install-all
else
  make -C "$INSTALL_DIR" install-all NO_VOICE=1
fi

if [ "$WITH_LLM" = 1 ]; then
  if ! has ollama; then
    step "Installing Ollama (local LLM runtime)"
    if [ "$OS" = Linux ]; then
      curl -fsSL https://ollama.com/install.sh | sh
    elif has brew; then
      brew install ollama
    else
      fail "Install Ollama from https://ollama.com/download, then run 'make install-llm' in $INSTALL_DIR."
    fi
  fi
  if ! curl -fsS http://localhost:11434/api/version >/dev/null 2>&1; then
    step "Starting Ollama"
    if [ "$OS" = Darwin ] && has brew && brew list ollama >/dev/null 2>&1; then
      brew services start ollama
    else
      nohup ollama serve >/dev/null 2>&1 &
    fi
    for _ in $(seq 1 30); do
      curl -fsS http://localhost:11434/api/version >/dev/null 2>&1 && break
      sleep 1
    done
  fi
  step "Downloading the local model (about 4 GB)"
  make -C "$INSTALL_DIR" install-llm
fi

cat <<EOF

==> Installed.

Next steps:
  cd "$INSTALL_DIR"
  make set-admin-password    # set the desk admin password
  make start-py              # start the server (Ctrl+C or 'make stop' stops it)

Then open http://localhost:8000/desk/, log in as "admin", and add your API
keys in Settings -> API Keys (Gemini is the default voice model).
Guide: components/install-doc.md
EOF
