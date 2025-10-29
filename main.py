"""
Entry point for the CI Fuzzer pipeline.
- Receives library name and commit hash as arguments
- Assumes the library is already cloned in ./libs/<library_name>
- Shows git diff and finds related public APIs
"""

import os
import argparse
from src.git_utils import show_git_diff, get_changed_functions
from src.lsp_analyzer import find_related_public_apis
from src.harness_generator import generate_harness_for_apis
from src.fuzzer_runner import validate_harnesses_with_fuzzing

def main():
    parser = argparse.ArgumentParser(description="CI Fuzzer Entry Point")
    parser.add_argument('--library', required=True, help='Library name (should exist in ./libs/<library>)')
    parser.add_argument('--commit', required=True, help='Git commit hash to diff')
    args = parser.parse_args()
    
    repo_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'libs', args.library))
    
    # 1. print git diff 
    show_git_diff(repo_path, args.commit)
    
    # 2. extract changed functions
    print("\n" + "="*60)
    print("[STEP 2] Extracting changed functions...")
    print("="*60)
    changed_functions = get_changed_functions(repo_path, args.commit)
    
    for file_path, functions in changed_functions.items():
        print(f"\n{file_path}:")
        for func in functions:
            print(f"  - {func}")
    
    # 3. find related public APIs
    print("\n" + "="*60)
    print("[STEP 3] Finding related public APIs using LSP...")
    print("="*60)
    related_apis = find_related_public_apis(repo_path, changed_functions)
    
    if related_apis:
        print(f"\n[RESULT] Found {len(related_apis)} related public APIs:")
        for api in sorted(related_apis):
            print(f"  - {api}")

        # 4. Generate harnesses using GPT (or offline fallback)
        project_root = os.path.dirname(os.path.abspath(__file__))
        out_dir = os.path.join(project_root, 'generated_harnesses', args.library)
        print("\n" + "="*60)
        print("[STEP 4] Generating harnesses for related public APIs (GPT/offline)...")
        print("="*60)
        outputs = generate_harness_for_apis(repo_path, args.library, related_apis, out_dir)
        if outputs:
            print(f"\n[HARNESS RESULT] Generated {len(outputs)} harness files:")
            for api, path in outputs.items():
                print(f"  - {api}: {path}")
            
            # 5. Run AFL fuzzer on each harness for quick validation
            print("\n" + "="*60)
            print("[STEP 5] Running AFL fuzzer for 10s validation...")
            print("="*60)
            fuzz_results = validate_harnesses_with_fuzzing(outputs, duration_secs=10)
            
            success_count = sum(1 for ok in fuzz_results.values() if ok)
            print(f"\n[FUZZ RESULT] {success_count}/{len(fuzz_results)} harnesses ran successfully with AFL")
            for api, success in fuzz_results.items():
                status = "✓ OK" if success else "✗ FAIL"
                print(f"  {status} {api}")
        else:
            print("\n[HARNESS RESULT] No harness files generated.")
    else:
        print("\n[RESULT] No directly related public APIs found.")

if __name__ == "__main__":
    main()
