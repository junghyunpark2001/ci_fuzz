#!/usr/bin/env python3
"""
Simple fuzzer runner. Run AFL on generated harnesses.

Usage:
    python3 run_fuzzer.py generated_harnesses/libxml2/harness_xmlFileClose
    python3 run_fuzzer.py generated_harnesses/libxml2/harness_xmlFileClose 3600
"""
import os
import sys
import subprocess
import tempfile
import shutil


def create_seeds(seed_dir):
    """Create basic seed files."""
    os.makedirs(seed_dir, exist_ok=True)
    seeds = [
        ("seed1.txt", b"hello"),
        ("seed2.xml", b"<?xml version='1.0'?><root>test</root>"),
        ("seed3.bin", b"A" * 100),
    ]
    for name, data in seeds:
        with open(os.path.join(seed_dir, name), 'wb') as f:
            f.write(data)


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 run_fuzzer.py <harness_binary> [duration_seconds]")
        print("Example: python3 run_fuzzer.py generated_harnesses/libxml2-8689523a/harness_xmlFileClose 3600")
        sys.exit(1)
    
    harness = sys.argv[1]
    duration = sys.argv[2] if len(sys.argv) > 2 else None
    
    # If user provided .c file, remove extension to get binary
    if harness.endswith('.c'):
        harness = harness[:-2]
        print(f"[INFO] Detected .c extension, using binary: {harness}")
    
    if not os.path.exists(harness):
        print(f"[ERROR] Harness not found: {harness}")
        sys.exit(1)
    
    # Infer library name and commit hash from harness path
    # Expected path format: generated_harnesses/libxml2-<hash>/harness_xxx
    harness_dir = os.path.dirname(harness)
    harness_dir_name = os.path.basename(harness_dir)
    
    # Extract lib_name and commit hash
    if '-' in harness_dir_name:
        lib_name, commit_hash = harness_dir_name.rsplit('-', 1)
    else:
        # Fallback: assume libxml2 with no specific commit
        lib_name = harness_dir_name
        commit_hash = None
    
    # Setup
    seed_dir = tempfile.mkdtemp(prefix="afl_seeds_")
    output_dir = f"afl_output/{os.path.basename(harness)}"
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    create_seeds(seed_dir)
    
    # Environment - use commit-specific build if available
    project_root = os.path.dirname(os.path.abspath(__file__))
    if commit_hash:
        # Use commit-specific build directory
        build_dir_name = f'{lib_name}-{commit_hash}'
        lib_path = os.path.join(project_root, 'afl_libs', build_dir_name, '.libs')
        print(f"[INFO] Using library from: {lib_path}")
    else:
        # Fallback to default path
        lib_path = os.path.join(project_root, 'afl_libs', lib_name, '.libs')
        print(f"[INFO] Using library from (fallback): {lib_path}")
    
    if not os.path.exists(lib_path):
        print(f"[ERROR] Library path not found: {lib_path}")
        print(f"[HINT] Make sure the library was built for commit {commit_hash}")
        sys.exit(1)
    
    env = os.environ.copy()
    env['LD_LIBRARY_PATH'] = lib_path + ':' + env.get('LD_LIBRARY_PATH', '')
    env['AFL_SKIP_CPUFREQ'] = '1'
    env['AFL_I_DONT_CARE_ABOUT_MISSING_CRASHES'] = '1'
    env['AFL_AUTORESUME'] = '1'
    
    # Command - Use AFL++ with libFuzzer mode (-L 0)
    # -L 0 tells AFL++ to use libFuzzer-compatible mode
    cmd = ['afl-fuzz', '-i', seed_dir, '-o', output_dir, '-L', '0']
    if duration:
        cmd.extend(['-V', duration])
    cmd.extend(['--', harness])
    
    print(f"[START] Fuzzing {harness}")
    print(f"[OUTPUT] {output_dir}")
    if duration:
        print(f"[DURATION] {duration} seconds")
    print("[INFO] Press Ctrl+C to stop\n")
    
    try:
        subprocess.run(cmd, env=env)
    except KeyboardInterrupt:
        print("\n[STOP] Fuzzing stopped")
    finally:
        shutil.rmtree(seed_dir, ignore_errors=True)
        
        # Report crashes
        crash_dir = os.path.join(output_dir, 'default', 'crashes')
        if os.path.isdir(crash_dir):
            crashes = [f for f in os.listdir(crash_dir) if f.startswith('id:')]
            if crashes:
                print(f"\n[RESULT] Found {len(crashes)} crashes in {crash_dir}")
            else:
                print(f"\n[RESULT] No crashes found")


if __name__ == "__main__":
    main()
