````markdown
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
python3 main.py --library libxml2 --commit 22f9d730
```