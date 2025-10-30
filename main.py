"""
Entry point for the CI Fuzzer pipeline.
- Receives library name and commit hash as arguments
- Checks out the library at the specified commit
- Builds it with AFL instrumentation in commit-specific directory
- Shows git diff and finds related public APIs
"""

import os
import sys
import argparse
import subprocess
from src.git_utils import show_git_diff, get_changed_functions
from src.lsp_analyzer import find_related_public_apis
from src.harness_generator import generate_harness_for_apis


def checkout_and_build_commit(repo_path: str, commit: str, lib_name: str) -> str:
    """
    Checkout the specified commit and build it.
    Returns the path to the built library directory.
    """
    # Get short commit hash for directory naming
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--short', commit],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        )
        short_hash = result.stdout.strip()
    except Exception as e:
        print(f"[ERROR] Failed to resolve commit {commit}: {e}")
        sys.exit(1)
    
    # Build directory for this commit
    project_root = os.path.dirname(os.path.abspath(__file__))
    build_dir = os.path.join(project_root, 'afl_libs', f'{lib_name}-{short_hash}')
    
    # Check if already built
    if os.path.exists(build_dir) and os.path.isdir(build_dir):
        print(f"[INFO] Using cached build for {lib_name}@{short_hash}: {build_dir}")
        return build_dir
    
    print(f"\n[BUILD] Checking out {lib_name}@{commit} and building with AFL...")
    
    # Checkout the commit
    try:
        subprocess.run(['git', 'checkout', commit], cwd=repo_path, check=True, capture_output=True)
        print(f"[BUILD] Checked out commit {short_hash}")
    except Exception as e:
        print(f"[ERROR] Failed to checkout {commit}: {e}")
        sys.exit(1)
    
    # Build with AFL
    build_script = os.path.join(project_root, 'build_lib.sh')
    try:
        env = os.environ.copy()
        env['BUILD_DIR'] = build_dir
        subprocess.run([build_script, lib_name], env=env, check=True, cwd=project_root)
        print(f"[BUILD] Built {lib_name}@{short_hash} → {build_dir}")
    except Exception as e:
        print(f"[ERROR] Build failed: {e}")
        sys.exit(1)
    
    return build_dir

def main():
    parser = argparse.ArgumentParser(description="CI Fuzzer Entry Point")
    parser.add_argument('--library', required=True, help='Library name (should exist in ./libs/<library>)')
    parser.add_argument('--commit', required=True, help='Git commit hash to analyze')
    args = parser.parse_args()
    
    repo_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'libs', args.library))
    
    if not os.path.exists(repo_path):
        print(f"[ERROR] Library not found: {repo_path}")
        sys.exit(1)
    
    # Checkout and build the specified commit
    build_dir = checkout_and_build_commit(repo_path, args.commit, args.library)
    
    # Extract short hash for output directory naming
    short_hash = os.path.basename(build_dir).split('-')[-1]
    
    # 1. print git diff 
    print("\n" + "="*60)
    print("[STEP 1] Git diff at commit")
    print("="*60)
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
    
    # 3. find related public APIs (using the built version)
    print("\n" + "="*60)
    print("[STEP 3] Finding related public APIs using LSP...")
    print("="*60)
    related_apis = find_related_public_apis(build_dir, changed_functions)
    
    if related_apis:
        print(f"\n[RESULT] Found {len(related_apis)} related public APIs:")
        for api in sorted(related_apis):
            print(f"  - {api}")

        # 4. Generate harnesses using GPT (or offline fallback)
        project_root = os.path.dirname(os.path.abspath(__file__))
        out_dir = os.path.join(project_root, 'generated_harnesses', f'{args.library}-{short_hash}')
        print("\n" + "="*60)
        print("[STEP 4] Generating harnesses for related public APIs (GPT/offline)...")
        print("="*60)
        outputs = generate_harness_for_apis(repo_path, args.library, related_apis, out_dir, build_dir_override=build_dir)
        if outputs:
            print(f"\n[HARNESS RESULT] Generated {len(outputs)} harness files:")
            for api, path in outputs.items():
                print(f"  - {api}: {path}")
        else:
            print("\n[HARNESS RESULT] No harness files generated.")
    else:
        print("\n[RESULT] No directly related public APIs found.")

if __name__ == "__main__":
    main()
