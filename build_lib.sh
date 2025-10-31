#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
LIBS_DIR="$ROOT_DIR/libs"

# Use BUILD_DIR from environment if set, otherwise default under afl_libs
AFL_BUILD_DIR="${BUILD_DIR:-}"

log() { echo -e "$@"; }

apt_install_once() {
    # Best-effort dependency install (skip if not available)
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update -y || true
        sudo apt-get install -y libtool bear cmake nasm pkg-config autoconf automake libtool make gcc g++ || true
    fi
}

set_afl_env() {
    export CC=afl-clang-fast
    export CXX=afl-clang-fast++
    export AR=llvm-ar
    export RANLIB=llvm-ranlib
    export AFL_USE_ASAN=1
    export AFL_USE_UBSAN=1
}

copy_common_artifacts() {
    local src_root="$1"
    local out_dir="$2"

    rm -rf "$out_dir"
    mkdir -p "$out_dir/.libs" "$out_dir/include" "$out_dir/src"

    # libs
    find "$src_root" -maxdepth 2 -type f \( -name "*.a" -o -name "*.so*" -o -name "*.la" \) -exec cp {} "$out_dir/.libs/" \; 2>/dev/null || true

    # headers (common locations)
    if [[ -d "$src_root/include" ]]; then
        cp -r "$src_root/include"/* "$out_dir/include/" 2>/dev/null || true
    fi
    # project-specific header roots
    for hdr in zlib.h zconf.h jpeglib.h jconfig.h; do
        if [[ -f "$src_root/$hdr" ]]; then cp "$src_root/$hdr" "$out_dir/include/"; fi
        if [[ -f "$src_root/libjpeg/$hdr" ]]; then cp "$src_root/libjpeg/$hdr" "$out_dir/include/"; fi
    done

    # compile_commands.json (varies by build system)
    if [[ -f "$src_root/compile_commands.json" ]]; then
        cp "$src_root/compile_commands.json" "$out_dir/"
    elif [[ -f "$src_root/build/compile_commands.json" ]]; then
        cp "$src_root/build/compile_commands.json" "$out_dir/"
    fi

    # copy sources for LSP context
    rsync -a --include='*/' --include='*.c' --include='*.cc' --include='*.cpp' --include='*.h' --include='*.hpp' --exclude='*' \
        "$src_root/" "$out_dir/src/" 2>/dev/null || true
}

build_libxml2() {
    local lib_name="libxml2"
    local repo_dir="$LIBS_DIR/$lib_name"
    local out_dir="${AFL_BUILD_DIR:-$ROOT_DIR/afl_libs/$lib_name}"

    log "[libxml2] Preparing build..."
    mkdir -p "$LIBS_DIR"
    if [[ ! -d "$repo_dir" ]]; then
        git clone https://github.com/GNOME/libxml2.git "$repo_dir"
    fi
    ( cd "$repo_dir" && git fetch --all --tags --prune )

    set_afl_env
    ( cd "$repo_dir" && ./autogen.sh )
    log "[libxml2] Building with AFL (bear)"
    ( cd "$repo_dir" && bear -- make -j"$(nproc)" )

    copy_common_artifacts "$repo_dir" "$out_dir"
}

build_zlib() {
    local lib_name="zlib"
    local repo_dir="$LIBS_DIR/$lib_name"
    local out_dir="${AFL_BUILD_DIR:-$ROOT_DIR/afl_libs/$lib_name}"

    log "[zlib] Preparing build..."
    mkdir -p "$LIBS_DIR"
    if [[ ! -d "$repo_dir" ]]; then
        git clone https://github.com/madler/zlib.git "$repo_dir"
    fi
    ( cd "$repo_dir" && git fetch --all --tags --prune )

    set_afl_env
    ( cd "$repo_dir" && CC=$CC ./configure )
    log "[zlib] Building with AFL (bear)"
    ( cd "$repo_dir" && bear -- make -j"$(nproc)" )

    copy_common_artifacts "$repo_dir" "$out_dir"
}

build_libjpeg() {
    # libjpeg-turbo (CMake)
    local lib_name="libjpeg"
    local repo_dir="$LIBS_DIR/$lib_name"
    local out_dir="${AFL_BUILD_DIR:-$ROOT_DIR/afl_libs/$lib_name}"

    log "[libjpeg] Preparing build..."
    mkdir -p "$LIBS_DIR"
    if [[ ! -d "$repo_dir" ]]; then
        git clone https://github.com/libjpeg-turbo/libjpeg-turbo.git "$repo_dir"
    fi
    ( cd "$repo_dir" && git fetch --all --tags --prune )

    set_afl_env
    mkdir -p "$repo_dir/build"
    ( cd "$repo_dir/build" \
        && cmake -DCMAKE_C_COMPILER="$CC" -DCMAKE_CXX_COMPILER="$CXX" \
                         -DCMAKE_BUILD_TYPE=RelWithDebInfo \
                         -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
                         -DENABLE_SHARED=ON .. )
    log "[libjpeg] Building with AFL"
    ( cd "$repo_dir/build" && make -j"$(nproc)" )

    copy_common_artifacts "$repo_dir/build" "$out_dir"
    # headers live under repo/include as well
    if [[ -d "$repo_dir" ]]; then
        rsync -a --include='*/' --include='*.h' --exclude='*' "$repo_dir/" "$out_dir/include/" 2>/dev/null || true
    fi
}

show_summary() {
    local dir="$1"
    echo ""
    echo "AFL build completed!"
    echo "Built libraries are in: $dir"
    echo ""
    echo "Directory structure:"
    find "$dir" -maxdepth 2 -type f \( -name "*.a" -o -name "*.so*" -o -name "compile_commands.json" \) | head -20
    echo ""
    echo "Build Summary:"
    local lib_count
    lib_count=$(find "$dir" -type f \( -name "*.a" -o -name "*.so*" \) | wc -l)
    echo "  Libraries: $lib_count"
    if [[ -f "$dir/compile_commands.json" ]]; then
        echo "  compile_commands.json: ✓"
    else
        echo "  compile_commands.json: ✗ (LSP analysis may not work)"
    fi
}

main() {
    apt_install_once
    mkdir -p "$LIBS_DIR"

    local target_lib="${1:-libxml2}"
    # If BUILD_DIR is not set, default under afl_libs/<lib>
    if [[ -z "${AFL_BUILD_DIR}" ]]; then
        AFL_BUILD_DIR="$ROOT_DIR/afl_libs/${target_lib}"
    fi
    echo "[INFO] Build directory: $AFL_BUILD_DIR"

    case "$target_lib" in
        libxml2)
            build_libxml2
            ;;
        zlib)
            build_zlib
            ;;
        libjpeg|libjpeg-turbo|jpeg)
            build_libjpeg
            ;;
        *)
            echo "[ERROR] Unknown library '$target_lib'. Supported: libxml2, zlib, libjpeg" >&2
            exit 2
            ;;
    esac

    show_summary "$AFL_BUILD_DIR"
}

main "$@"