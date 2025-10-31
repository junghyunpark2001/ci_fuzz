"""
clangd LSP를 사용하여 public API 추출 및 call graph 분석
"""
import os
import subprocess
import json
import re
from typing import Set, List, Dict
from .lsp_client import build_call_graph_with_lsp

def find_public_apis(build_dir: str) -> Set[str]:
    """
    Extract public API functions from built libraries using nm
    If failed, fallback to extract using regex from include/ headers
    
    Args:
        build_dir: Path to the commit-specific build directory (e.g., afl_libs/libxml2-<hash>)
    """
    public_apis = set()
    lib_dirs = [
        os.path.join(build_dir, '.libs'),
        build_dir,
    ]
    tried_files = set()
    found_any = False
    for lib_dir in lib_dirs:
        if not os.path.isdir(lib_dir):
            continue
        for file in os.listdir(lib_dir):
            if file.endswith(('.a', '.so', '.la')):
                lib_path = os.path.join(lib_dir, file)
                tried_files.add(lib_path)
                try:
                    result = subprocess.run(
                        ['nm', '-g', '--defined-only', lib_path],
                        capture_output=True, text=True, check=True
                    )
                    for line in result.stdout.splitlines():
                        parts = line.split()
                        if len(parts) == 3 and parts[1] == 'T':
                            public_apis.add(parts[2])
                    found_any = found_any or bool(public_apis)
                except Exception as e:
                    print(f"[ERROR] nm failed for {lib_path}: {e}")
    if public_apis:
        print(f"[INFO] Extracted {len(public_apis)} public APIs from: {', '.join(tried_files)}")
        print(f"[DEBUG] Sample public APIs: {list(public_apis)[:10]}")
        return public_apis
    # Fallback: include/ 헤더에서 정규식 추출
    print("[WARN] No public APIs found in built libraries, falling back to include/ header scan.")
    include_dir = os.path.join(build_dir, 'include')
    if not os.path.isdir(include_dir):
        print(f"[WARN] include directory not found: {include_dir}")
        return public_apis
    for root, dirs, files in os.walk(include_dir):
        for file in files:
            if file.endswith(('.h', '.hpp')):
                header_path = os.path.join(root, file)
                with open(header_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    pattern = r'\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\([^)]*\)\s*;'
                    matches = re.findall(pattern, content)
                    public_apis.update(matches)
    print(f"[INFO] Extracted {len(public_apis)} public APIs from headers (fallback)")
    print(f"[DEBUG] Sample public APIs: {list(public_apis)[:10]}")
    
    return public_apis

def find_compile_commands(build_dir: str) -> str:
    """find or generate compile_commands.json
    
    Args:
        build_dir: Path to the commit-specific build directory (e.g., afl_libs/libxml2-<hash>)
    """
    compile_commands_path = os.path.join(build_dir, 'compile_commands.json')
    
    if os.path.exists(compile_commands_path):
        return compile_commands_path
    
    # bear를 사용하여 compile_commands.json 생성
    print("[INFO] Generating compile_commands.json with bear...")
    try:
        subprocess.run(['bear', '--', 'make', '-j'], cwd=build_dir, check=True)
        if os.path.exists(compile_commands_path):
            return compile_commands_path
    except Exception as e:
        print(f"[WARN] Failed to generate compile_commands.json: {e}")
    
    return None

def find_related_public_apis(build_dir: str, changed_functions: Dict[str, Set[str]]) -> Set[str]:
    """
    Find public APIs related to changed functions
    1. extract public API list
    2. check if changed functions are public APIs (direct relation)
    3. analyze call graph to find indirectly related APIs
    
    Args:
        build_dir: Path to the commit-specific build directory (e.g., afl_libs/libxml2-<hash>)
        changed_functions: Dict mapping file paths to sets of changed function names
    """
    public_apis = find_public_apis(build_dir)
    related_apis = set()
    

    # Among changed functions, find those that are public APIs (direct relation)
    print("\n[STEP 3.1] Finding directly related public APIs...")
    for file_path, functions in changed_functions.items():
        for func in functions:
            if func in public_apis:
                related_apis.add(func)
                print(f"[DIRECT] Changed function '{func}' is a public API")
    
    # Build call graph to find indirectly related APIs
    print("\n[STEP 3.2] Building call graph to find indirectly related APIs...")
    print("[INFO] This may take a while...")
    
    indirect_apis = build_call_graph_with_lsp(build_dir, changed_functions, public_apis, max_depth=10)
    
    # exclude directly related APIs
    indirect_apis = indirect_apis - related_apis
    
    if indirect_apis:
        print(f"\n[INDIRECT] Found {len(indirect_apis)} indirectly related public APIs:")
        for api in sorted(indirect_apis):
            print(f"  - {api}")
    else:
        print("\n[INDIRECT] No indirectly related public APIs found.")
    
    # Sum up all related APIs
    all_related_apis = related_apis | indirect_apis
    
    return all_related_apis
