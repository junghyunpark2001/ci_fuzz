#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
LIBS_DIR="$ROOT_DIR/libs"
LIBXML2_DIR="$LIBS_DIR/libxml2"
GIT_URL="https://github.com/GNOME/libxml2.git"

# Use BUILD_DIR from environment if set, otherwise use default
if [[ -z "${BUILD_DIR:-}" ]]; then
    AFL_BUILD_DIR="$ROOT_DIR/afl_libs/libxml2"
else
    AFL_BUILD_DIR="$BUILD_DIR"
fi

echo "[INFO] Build directory: $AFL_BUILD_DIR"

sudo apt-get update
sudo apt-get install -y libtool bear

echo "[libxml2] Preparing build environment..."
mkdir -p "$LIBS_DIR"
mkdir -p "$AFL_BUILD_DIR"

if [[ ! -d "$LIBXML2_DIR" ]]; then
    echo "[libxml2] Cloning libxml2..."
    git clone "$GIT_URL" "$LIBXML2_DIR"
else
    echo "[libxml2] Already cloned."
fi

cd "$LIBXML2_DIR"
git fetch
# 최신 커밋을 사용하려면 아래 checkout 라인에 원하는 커밋 해시를 지정하세요.
# git checkout <commit_hash>

echo "[libxml2] Initializing submodules..."
git submodule update --init --recursive

echo "[libxml2] Setting AFL environment..."
export CC=afl-clang-fast
export CXX=afl-clang-fast++
export AR=llvm-ar
export RANLIB=llvm-ranlib
export AFL_USE_ASAN=1
export AFL_USE_UBSAN=1

echo "[libxml2] Running autogen.sh..."
./autogen.sh

echo "[libxml2] Building with AFL and generating compile_commands.json..."
bear -- make -j$(nproc)

# copy built files into AFL_BUILD_DIR
rm -rf "$AFL_BUILD_DIR"
mkdir -p "$AFL_BUILD_DIR"
cp -r .libs "$AFL_BUILD_DIR/" 2>/dev/null || true
cp -r include "$AFL_BUILD_DIR/" 2>/dev/null || true
cp *.la "$AFL_BUILD_DIR/" 2>/dev/null || true
cp *.so* "$AFL_BUILD_DIR/" 2>/dev/null || true

# Copy compile_commands.json for LSP analysis
if [[ -f "compile_commands.json" ]]; then
    echo "[INFO] Copying compile_commands.json to build directory..."
    cp compile_commands.json "$AFL_BUILD_DIR/"
else
    echo "[WARN] compile_commands.json not found in source directory"
fi

# Also copy source files for LSP to work properly
echo "[INFO] Copying source files for LSP analysis..."
rsync -a --include='*/' --include='*.c' --include='*.h' --exclude='*' . "$AFL_BUILD_DIR/src/" 2>/dev/null || true

echo ""
echo "AFL build completed!"
echo "Built libraries are in: $AFL_BUILD_DIR"
echo ""
echo "Directory structure:"
find "$AFL_BUILD_DIR" -name "*.a" -o -name "*.so" -o -name "compile_commands.json" | head -20

echo ""
echo "Build Summary:"
lib_count=$(find "$AFL_BUILD_DIR" -name "*.a" -o -name "*.so" | wc -l)
echo "  Libraries: $lib_count"
if [[ -f "$AFL_BUILD_DIR/compile_commands.json" ]]; then
    echo "  compile_commands.json: ✓"
else
    echo "  compile_commands.json: ✗ (LSP analysis may not work)"
fi