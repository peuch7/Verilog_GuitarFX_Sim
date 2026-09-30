#!/usr/bin/env bash
#
# One-command setup for macOS and Linux (including WSL2).
#
#   ./scripts/bootstrap.sh        or        make setup
#
# Installs the simulators if they are missing, then creates .venv and installs
# the Python package into it. Safe to run repeatedly: everything is a no-op once
# it is already in place.
#
# Windows without WSL is not supported here; use the container instead.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

say() { printf '\n==> %s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

case "$(uname -s)" in
    Darwin) OS=macos ;;
    Linux)  OS=linux ;;
    *)
        echo "Unsupported system: $(uname -s)."
        echo "On Windows, use the container: open this folder in VS Code and choose"
        echo "'Reopen in Container', or run  .\\wavsim.ps1 setup"
        exit 1
        ;;
esac

# ---------------------------------------------------------------- simulators

install_macos() {
    if ! have brew; then
        echo "Homebrew is not installed. Get it from https://brew.sh, then rerun this."
        exit 1
    fi
    have verilator || { say "Installing verilator"; brew install verilator; }
    have iverilog  || { say "Installing icarus-verilog"; brew install icarus-verilog; }
}

install_linux() {
    if ! have apt-get; then
        echo "This script only knows apt. Install these with your package manager, then rerun:"
        echo "  verilator iverilog build-essential python3-venv"
        exit 1
    fi
    local missing=()
    have verilator || missing+=(verilator)
    have iverilog  || missing+=(iverilog)
    have c++       || missing+=(build-essential)
    python3 -c 'import venv' 2>/dev/null || missing+=(python3-venv)

    if [ ${#missing[@]} -gt 0 ]; then
        say "Installing: ${missing[*]}"
        sudo apt-get update
        sudo apt-get install -y "${missing[@]}"
    fi
}

if [ "${SKIP_TOOLCHAIN:-0}" != "1" ]; then
    case "$OS" in
        macos) install_macos ;;
        linux) install_linux ;;
    esac
else
    say "SKIP_TOOLCHAIN=1, leaving the simulators alone"
fi

# -------------------------------------------------------------------- python

PYTHON="${PYTHON:-python3}"
if [ ! -d .venv ]; then
    say "Creating .venv"
    "$PYTHON" -m venv .venv
fi

say "Installing the wavsim package"
./.venv/bin/python -m pip install --upgrade pip --quiet
./.venv/bin/python -m pip install -e ".[dev]" --quiet

# -------------------------------------------------------------------- verify

say "Checking the result"
./.venv/bin/python scripts/doctor.py

cat <<'EOF'

Setup finished. Nothing needs activating — every make target uses .venv
automatically. Try:

  make run effect=delay
  make compare effect=delay
  make test

EOF
