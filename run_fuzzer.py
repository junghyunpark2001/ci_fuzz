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
        print("Example: python3 run_fuzzer.py generated_harnesses/libxml2/harness_xmlFileClose 3600")
        sys.exit(1)
    
    harness = sys.argv[1]
    duration = sys.argv[2] if len(sys.argv) > 2 else None
    
    if not os.path.exists(harness):
        print(f"[ERROR] Harness not found: {harness}")
        sys.exit(1)
    
    # Setup
    seed_dir = tempfile.mkdtemp(prefix="afl_seeds_")
    output_dir = f"afl_output/{os.path.basename(harness)}"
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    create_seeds(seed_dir)
    
    # Environment
    project_root = os.path.dirname(os.path.abspath(__file__))
    lib_path = os.path.join(project_root, 'afl_libs', 'libxml2', '.libs')
    env = os.environ.copy()
    env['LD_LIBRARY_PATH'] = lib_path + ':' + env.get('LD_LIBRARY_PATH', '')
    env['AFL_SKIP_CPUFREQ'] = '1'
    env['AFL_I_DONT_CARE_ABOUT_MISSING_CRASHES'] = '1'
    env['AFL_AUTORESUME'] = '1'
    
    # Command
    cmd = ['afl-fuzz', '-i', seed_dir, '-o', output_dir]
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
