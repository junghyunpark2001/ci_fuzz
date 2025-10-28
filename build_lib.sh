#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
LIBS_DIR="$ROOT_DIR/libs"
AFL_BUILD_DIR="$ROOT_DIR/afl_libs"
LIBXML2_DIR="$LIBS_DIR/libxml2"
GIT_URL="https://github.com/GNOME/libxml2.git"

sudo apt-get update
sudo apt-get install -y libtool

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

echo "[libxml2] Building with AFL..."
make -j$(nproc)

# copy built files into afl_libs/libxml2/
rm -rf "$AFL_BUILD_DIR/libxml2"
mkdir -p "$AFL_BUILD_DIR/libxml2"
cp -r .libs "$AFL_BUILD_DIR/libxml2/" 2>/dev/null || true
cp -r include "$AFL_BUILD_DIR/libxml2/" 2>/dev/null || true
cp -r *.la *.so* "$AFL_BUILD_DIR/libxml2/" 2>/dev/null || true

echo ""
echo "AFL build completed!"
echo "Built libraries are in: $AFL_BUILD_DIR"
echo ""
echo "Directory structure:"
find "$AFL_BUILD_DIR" -name "*.a" -o -name "*.h" | head -20

echo ""
echo "Build Summary:"
for lib_dir in "$AFL_BUILD_DIR"/*; do
    if [[ -d "$lib_dir" ]]; then
        lib_name=$(basename "$lib_dir")
        lib_count=$(find "$lib_dir" -name "*.a" | wc -l)
        echo "  $lib_name: $lib_count static libraries"
    fi
done