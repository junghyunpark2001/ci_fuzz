"""
AFL fuzzer runner for quick validation of generated harnesses.
Runs each harness for a short duration to verify it works with AFL.
"""
import os
import subprocess
import tempfile
import shutil
from typing import Dict, List, Tuple


def create_seed_corpus(seed_dir: str) -> None:
    """Create minimal seed corpus for AFL."""
    os.makedirs(seed_dir, exist_ok=True)
    
    # Create a few basic seed files
    seeds = [
        ("seed1.txt", b"hello"),
        ("seed2.txt", b"<xml>test</xml>"),
        ("seed3.txt", b"A" * 100),
        ("seed4.txt", b"\x00\x01\x02\x03"),
    ]
    
    for name, content in seeds:
        with open(os.path.join(seed_dir, name), 'wb') as f:
            f.write(content)


def run_afl_fuzz(harness_path: str, duration_secs: int = 10) -> Tuple[bool, str]:
    """
    Run AFL fuzzer on the harness for a short duration.
    Returns (success: bool, output: str)
    """
    if not os.path.exists(harness_path):
        return (False, f"Harness not found: {harness_path}")
    
    # Create temporary directories for AFL
    temp_base = tempfile.mkdtemp(prefix="afl_test_")
    seed_dir = os.path.join(temp_base, "input")
    out_dir = os.path.join(temp_base, "output")
    
    try:
        create_seed_corpus(seed_dir)
        
        # Set library path for runtime
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        lib_path = os.path.join(project_root, 'afl_libs', 'libxml2', '.libs')
        env = os.environ.copy()
        env['LD_LIBRARY_PATH'] = lib_path + ':' + env.get('LD_LIBRARY_PATH', '')
        env['AFL_SKIP_CPUFREQ'] = '1'  # Skip CPU freq warning
        env['AFL_I_DONT_CARE_ABOUT_MISSING_CRASHES'] = '1'  # Skip crash dir warning
        
        # Run AFL with timeout
        cmd = [
            'timeout', f'{duration_secs}s',
            'afl-fuzz',
            '-i', seed_dir,
            '-o', out_dir,
            '-V', str(duration_secs),  # Max runtime
            '-d',  # Skip deterministic stage (faster)
            '--',
            harness_path,
        ]
        
        print(f"[FUZZ] Starting AFL for {duration_secs}s: {os.path.basename(harness_path)}")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            timeout=duration_secs + 5,  # Extra buffer
        )
        
        # Check if AFL ran (timeout means it ran successfully for the duration)
        output = result.stdout + result.stderr
        
        # Look for AFL statistics to confirm it ran
        if 'total execs' in output or 'execs_per_sec' in output or result.returncode in [0, 124]:  # 124 = timeout
            # Count any crashes/hangs
            crash_dir = os.path.join(out_dir, 'default', 'crashes')
            hang_dir = os.path.join(out_dir, 'default', 'hangs')
            
            crashes = 0
            hangs = 0
            
            if os.path.isdir(crash_dir):
                crashes = len([f for f in os.listdir(crash_dir) if f.startswith('id:')])
            if os.path.isdir(hang_dir):
                hangs = len([f for f in os.listdir(hang_dir) if f.startswith('id:')])
            
            summary = f"AFL ran successfully. Crashes: {crashes}, Hangs: {hangs}"
            print(f"[FUZZ OK] {summary}")
            return (True, summary)
        else:
            return (False, f"AFL failed to start or run properly: {output[:500]}")
            
    except subprocess.TimeoutExpired:
        # Timeout is actually success - it means AFL ran for the full duration
        print(f"[FUZZ OK] AFL completed {duration_secs}s run")
        return (True, f"AFL ran for {duration_secs}s")
    except Exception as e:
        return (False, f"Fuzzing error: {str(e)}")
    finally:
        # Cleanup
        try:
            shutil.rmtree(temp_base, ignore_errors=True)
        except:
            pass


def validate_harnesses_with_fuzzing(harness_files: Dict[str, str], duration_secs: int = 10) -> Dict[str, bool]:
    """
    Run AFL on each harness for quick validation.
    Returns a map: api_name -> fuzzing_success
    """
    results = {}
    
    for api, harness_path in harness_files.items():
        # Convert .c to binary path
        binary_path = harness_path.replace('.c', '')
        
        if not os.path.exists(binary_path):
            print(f"[FUZZ SKIP] Binary not found for {api}: {binary_path}")
            results[api] = False
            continue
        
        success, msg = run_afl_fuzz(binary_path, duration_secs)
        results[api] = success
        
        if not success:
            print(f"[FUZZ FAIL] {api}: {msg}")
    
    return results


if __name__ == "__main__":
    # Quick test
    pass
