#!/usr/bin/env bash
set -euo pipefail

# Project root
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "[0/3] Creating Python virtual environment..."
if [ ! -d "$ROOT_DIR/venv" ]; then
    python3 -m venv "$ROOT_DIR/venv"
    echo "Virtual environment created at $ROOT_DIR/venv"
else
    echo "Virtual environment already exists at $ROOT_DIR/venv"
fi

echo "Activating virtual environment..."
source "$ROOT_DIR/venv/bin/activate"

echo "[1/3] Installing required packages and dependencies..."
# Install system packages if sudo is available
command -v sudo >/dev/null 2>&1 && {
    sudo apt-get update -y
    sudo apt-get install -y git build-essential bear llvm-dev
} 

# Install Python dependencies
python3 -m pip install --upgrade pip -r "$ROOT_DIR/requirements.txt"



echo "[2/3] Cloning and installing AFL++ (sudo install)..."
cd "$ROOT_DIR"
if [ ! -d "$ROOT_DIR/AFLplusplus" ]; then
  git clone https://github.com/AFLplusplus/AFLplusplus.git
fi

cd AFLplusplus
make distrib -j"$(nproc)"
sudo make install

echo "[3/3] Setup complete!"
echo ""
echo "To activate the virtual environment in future sessions, run:"
echo "  source $ROOT_DIR/venv/bin/activate"
echo ""
echo "You can now use afl-clang-fast and afl-fuzz."


