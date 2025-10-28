"""
Extern API 추출을 위해 clangd LSP를 활용하는 모듈 (최소 예시)
실제 사용시 python-lsp, clangd, 혹은 ccls와 연동 필요
"""
import subprocess
from typing import List, Set
import os

def get_extern_apis_with_clangd(header_files: List[str], compile_commands_path: str = None) -> Set[str]:
    """
    clangd를 통해 extern "C" API 함수 목록을 추출 (stub: 실제 LSP 연동 필요)
    실제 구현시 python-lsp-server, clangd, 혹은 ccls와 연동하여 심볼 정보 추출
    """
    apis = set()
    for header in header_files:
        with open(header) as f:
            for line in f:
                if 'extern' in line and '(' in line:
                    fn = line.split('(')[0].split()[-1].strip(';')
                    apis.add(fn)
    return apis

if __name__ == "__main__":
    # 예시: print(get_extern_apis_with_clangd(['../include/library.h']))
    pass
