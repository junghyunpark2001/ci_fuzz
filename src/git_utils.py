"""
Git 관련 유틸리티 함수 모듈
"""
import os
import subprocess
import re
from typing import List, Set, Dict

def show_git_diff(repo_path: str, commit: str):
    if not os.path.isdir(repo_path):
        print(f"[ERROR] Library directory not found: {repo_path}")
        return
    try:
        result = subprocess.run([
            'git', '-C', repo_path, 'diff', f'{commit}^!',
        ], capture_output=True, text=True, check=True)
        print(f"\n[git diff at {commit}]:\n")
        print(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] git diff failed: {e.stderr}")

def get_changed_files(repo_path: str, commit: str) -> List[str]:
    """return files changed in the commit"""
    result = subprocess.run([
        'git', '-C', repo_path, 'diff', '--name-only', f'{commit}^!'
    ], capture_output=True, text=True, check=True)
    return [f for f in result.stdout.strip().split('\n') if f]

def get_changed_functions(repo_path: str, commit: str) -> Dict[str, Set[str]]:
    """
    Get changed functions in the commit
    """
    changed_files = get_changed_files(repo_path, commit)
    print(f"changed_files: {changed_files}")
    functions_by_file = {}
    
    for file_path in changed_files:
        if not file_path.endswith(('.c', '.cpp', '.cc', '.h', '.hpp')):
            continue
        
        result = subprocess.run([
            'git', '-C', repo_path, 'diff', f'{commit}^!', '--', file_path
        ], capture_output=True, text=True, check=True)
        
        functions = set()
        for line in result.stdout.split('\n'):
            if line.startswith('@@'):
                # @@ -old +new @@ function_name 형식에서 함수명 추출
                match = re.search(r'@@.*@@\s*(.+)', line)
                if match:
                    func_name = match.group(1).strip()
                    # 함수명만 추출 (파라미터 등 제거)
                    func_name = re.sub(r'\(.*', '', func_name).strip()
                    if func_name:
                        functions.add(func_name)
        
        if functions:
            functions_by_file[file_path] = functions
    return functions_by_file
