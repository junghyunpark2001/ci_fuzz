````markdown
# CI LLM Fuzzer

Automatically produce a usable fuzzing harness for a specified library + commit, run fuzzers in CI.

## Quick Start

### Program Setup


# CI LLM Fuzzer

Automatically produce a usable fuzzing harness for a specified library + commit, run fuzzers in CI.

## Quick Start

### Program Setup

```bash
# project root directory
./setup.sh
```

### One-Shot Pipeline (Analysis + Harness Generation + Quick Validation)

```bash
# Start virtual environment
source venv/bin/activate

# With GPT harness generation (optional but strongly recommend)
export OPENAI_API_KEY="sk-..."

# Analyze commit and generate harnesses
python3 main.py --library <library-name> --commit <commit>
```

### Continuous Fuzzing (Independent of Pipeline)

```bash
# Fuzz forever (Ctrl+C to stop)
python3 run_fuzzer.py generated_harnesses/libxml2/harness_xmlFileClose

# Fuzz for 1 hour
python3 run_fuzzer.py generated_harnesses/libxml2/harness_xmlFileClose 3600

# finish virtual environment
deactivate
```

## Features

- **Automated Public API Discovery**: Uses git diff + LSP call graphs + nm symbol extraction
- **GPT-Powered Harness Generation**: Generates compilable AFL harnesses with GPT-4 (optional)
- **Build Validation**: Compiles harnesses with AFL and retries on errors (up to 3 attempts)
- **Quick Fuzzing Test**: Runs AFL for 10s to verify each harness works
- **Standalone Fuzzer**: `run_fuzzer.py` for long-running, parallel fuzzing sessions
- **Real-time Monitoring**: Live stats (execs/sec, crashes, paths)

## Pipeline Overview

**main.py** (5 steps):
1. Show git diff at specified commit
2. Extract changed functions from diff
3. Find related public APIs using LSP + nm
4. Generate harnesses (GPT or offline stub) + compile with AFL
5. Quick 10s AFL validation

**run_fuzzer.py** (continuous):
- Run AFL fuzzer indefinitely or for custom duration
- Support multiple parallel instances (e.g., `-j 8`)
- Monitor crashes/hangs in real-time
- Resume previous fuzzing sessions automatically

## Examples

```bash
# Full pipeline
python3 main.py --library libxml2 --commit 8689523a
python3 main.py --library libxml2 --commit 17d950ae
```

## Adding a new library

- Provide a build script at the repo root named `build_<lib>.sh` (executable). If absent, extend `build_lib.sh`'s case switch. `main.py` will call it as: `BUILD_DIR=<out> ./build_<lib>.sh <lib>`.
- Script contract: MUST populate `$BUILD_DIR` with the following after a successful build:
  - `$BUILD_DIR/include/` — public headers
  - `$BUILD_DIR/.libs/` — built libraries (`*.so*`, `*.a`)
  - `$BUILD_DIR/compile_commands.json` — required for clangd/LSP (use `bear -- make ...` or CMake with `-DCMAKE_EXPORT_COMPILE_COMMANDS=ON`)
  - `$BUILD_DIR/src/` — sources (copy or rsync only .c/.cc/.cpp/.h)
- Use AFL compilers in the script: `CC=afl-clang-fast`, `CXX=afl-clang-fast++` (set via `export`). Exit non-zero on failure.
- Quick check: `tree $BUILD_DIR` should show include/, .libs/, compile_commands.json, and src/.

Minimal script template:

```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
LIB="$1"                           # e.g., zlib
OUT_DIR="${BUILD_DIR:?missing}"    # set by main.py
SRC="$ROOT/libs/$LIB"              # your checked-out repo

export CC=afl-clang-fast CXX=afl-clang-fast++

# configure & build (examples)
# (cd "$SRC" && ./configure); (cd "$SRC" && bear -- make -j"$(nproc)")
# or CMake: (cd "$SRC" && mkdir -p build && cd build \
#   && cmake -DCMAKE_C_COMPILER=$CC -DCMAKE_CXX_COMPILER=$CXX -DCMAKE_EXPORT_COMPILE_COMMANDS=ON .. \
#   && make -j"$(nproc)")

rm -rf "$OUT_DIR"; mkdir -p "$OUT_DIR/.libs" "$OUT_DIR/include" "$OUT_DIR/src"
find "$SRC" -maxdepth 2 -type f \( -name "*.so*" -o -name "*.a" -o -name "*.la" \) -exec cp {} "$OUT_DIR/.libs/" \; || true
[[ -f "$SRC/compile_commands.json" ]] && cp "$SRC/compile_commands.json" "$OUT_DIR/" || true
[[ -f "$SRC/build/compile_commands.json" ]] && cp "$SRC/build/compile_commands.json" "$OUT_DIR/" || true
rsync -a --include='*/' --include='*.c' --include='*.cc' --include='*.cpp' --include='*.h' --exclude='*' "$SRC/" "$OUT_DIR/src/" || true
[[ -d "$SRC/include" ]] && cp -r "$SRC/include/"* "$OUT_DIR/include/" || true
```