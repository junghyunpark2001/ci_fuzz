"""
clangd LSP 클라이언트를 사용하여 call graph 분석
실제 clangd와 JSON-RPC 통신하여 call hierarchy 정보 추출
"""
import os
import json
import subprocess
import time
from typing import Set, Dict, List, Optional
from pathlib import Path
import threading
import re

class ClangdLSPClient:
    """client for communicating with clangd LSP server via JSON-RPC"""

    def __init__(self, build_dir: str):
        """Initialize clangd client with build directory
        
        Args:
            build_dir: Path to the commit-specific build directory containing compile_commands.json
        """
        self.build_dir = build_dir
        self.process = None
        self.msg_id = 0
        self.responses = {}
        self.reader_thread = None
        
    def start(self):
        """Start the clangd LSP server"""
        compile_commands = os.path.join(self.build_dir, 'compile_commands.json')
        if not os.path.exists(compile_commands):
            print(f"[WARN] compile_commands.json not found at {compile_commands}")
            print("[INFO] Attempting to generate with bear...")
            try:
                subprocess.run(['bear', '--', 'make', '-j'], cwd=self.build_dir, 
                             timeout=300, check=False)
            except Exception as e:
                print(f"[WARN] Could not generate compile_commands.json: {e}")
            
        try:
            self.process = subprocess.Popen(
                ['clangd', '--compile-commands-dir=' + self.build_dir, '--background-index'],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.build_dir,
                bufsize=0
            )
            
            # start reading responses thread
            self.reader_thread = threading.Thread(target=self._read_responses, daemon=True)
            self.reader_thread.start()
            
            # send initialize request
            response = self._send_request('initialize', {
                "processId": os.getpid(),
                "rootUri": f"file://{self.build_dir}",
                "capabilities": {
                    "textDocument": {
                        "callHierarchy": {
                            "dynamicRegistration": False
                        }
                    }
                }
            })
            
            # initialized 알림 전송
            self._send_notification('initialized', {})
            
            time.sleep(1)  # clangd 초기화 대기
            return True
            
        except Exception as e:
            print(f"[ERROR] Failed to start clangd: {e}")
            return False
    
    def _read_responses(self):
        """백그라운드에서 clangd 응답 읽기"""
        buffer = b""
        while self.process and self.process.poll() is None:
            try:
                chunk = self.process.stdout.read(1024)
                if not chunk:
                    break
                buffer += chunk
                
                # Content-Length 헤더 찾기
                while b'\r\n\r\n' in buffer:
                    header_end = buffer.index(b'\r\n\r\n')
                    headers = buffer[:header_end].decode('utf-8')
                    
                    content_length = 0
                    for line in headers.split('\r\n'):
                        if line.startswith('Content-Length:'):
                            content_length = int(line.split(':')[1].strip())
                            break
                    
                    if len(buffer) >= header_end + 4 + content_length:
                        content = buffer[header_end + 4:header_end + 4 + content_length]
                        buffer = buffer[header_end + 4 + content_length:]
                        
                        try:
                            msg = json.loads(content.decode('utf-8'))
                            if 'id' in msg:
                                self.responses[msg['id']] = msg
                        except json.JSONDecodeError:
                            pass
                    else:
                        break
            except Exception:
                break
    
    def _send_request(self, method: str, params: dict) -> Optional[dict]:
        """LSP 요청 전송 및 응답 대기"""
        msg = {
            "jsonrpc": "2.0",
            "id": self.msg_id,
            "method": method,
            "params": params
        }
        
        current_id = self.msg_id
        self.msg_id += 1
        
        self._send_message(msg)
        
        # 응답 대기 (최대 5초)
        for _ in range(50):
            if current_id in self.responses:
                return self.responses.pop(current_id)
            time.sleep(0.1)
        
        return None
    
    def _send_notification(self, method: str, params: dict):
        """LSP 알림 전송 (응답 없음)"""
        msg = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }
        self._send_message(msg)
    
    def _send_message(self, msg: dict):
        """LSP 메시지 전송"""
        content = json.dumps(msg)
        header = f"Content-Length: {len(content)}\r\n\r\n"
        try:
            self.process.stdin.write((header + content).encode('utf-8'))
            self.process.stdin.flush()
        except Exception as e:
            print(f"[ERROR] Failed to send message: {e}")
    
    def open_document(self, file_path: str) -> bool:
        """문서 열기"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read()
            
            self._send_notification('textDocument/didOpen', {
                "textDocument": {
                    "uri": f"file://{file_path}",
                    "languageId": "cpp" if file_path.endswith('.cpp') else "c",
                    "version": 1,
                    "text": text
                }
            })
            time.sleep(0.5)  # 인덱싱 대기
            return True
        except Exception as e:
            print(f"[ERROR] Failed to open document: {e}")
            return False
    
    def get_incoming_calls(self, file_path: str, function_name: str) -> Set[str]:
        """find incoming calls to a specific function"""
        callers = set()
        
        # find function definition location in the file
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            
            line_num = -1
            for i, line in enumerate(lines):
                # 함수 정의 패턴 찾기 (간단한 휴리스틱)
                if re.search(rf'\b{re.escape(function_name)}\s*\(', line):
                    line_num = i
                    break
            
            if line_num == -1:
                return callers
            
            # 문서 열기
            self.open_document(file_path)
            
            # prepareCallHierarchy 요청
            response = self._send_request('textDocument/prepareCallHierarchy', {
                "textDocument": {"uri": f"file://{file_path}"},
                "position": {"line": line_num, "character": 0}
            })
            
            if not response or 'result' not in response or not response['result']:
                return callers
            
            # callHierarchy/incomingCalls 요청
            for item in response['result']:
                incoming_response = self._send_request('callHierarchy/incomingCalls', {
                    "item": item
                })
                
                if incoming_response and 'result' in incoming_response:
                    for call in incoming_response['result']:
                        if 'from' in call and 'name' in call['from']:
                            caller_name = call['from']['name']
                            callers.add(caller_name)
                            print(f"[LSP] Found caller: {caller_name} -> {function_name}")
        
        except Exception as e:
            print(f"[ERROR] get_incoming_calls failed: {e}")
        
        return callers
    
    def stop(self):
        """clangd 서버 종료"""
        if self.process:
            try:
                self._send_request('shutdown', {})
                self._send_notification('exit', {})
                time.sleep(0.5)
            except:
                pass
            
            self.process.terminate()
            self.process.wait(timeout=5)

def build_call_graph_with_lsp(build_dir: str, changed_functions: Dict[str, Set[str]], 
                              public_apis: Set[str], max_depth: int = 3) -> Set[str]:
    """
    Using clangd LSP to build call graph and find related public APIs
    
    Args:
        build_dir: Path to the commit-specific build directory containing compile_commands.json
        changed_functions: Dict mapping file paths to sets of changed function names
        public_apis: Set of known public API function names
        max_depth: Maximum call chain depth to explore
    """
    related_apis = set()
    
    # start clangd
    client = ClangdLSPClient(build_dir)
    if not client.start():
        print("[ERROR] Failed to start clangd, falling back to simple analysis")
        return build_call_graph_simple(build_dir, changed_functions, public_apis, max_depth)
    
    print("[INFO] clangd LSP server started successfully")
    
    try:
        visited = set()
        
        # start from each changed function
        for file_path, functions in changed_functions.items():
            full_file_path = os.path.join(build_dir, file_path)
            
            if not os.path.exists(full_file_path):
                continue
            
            for func in functions:
                # using BFS to explore call chains
                queue = [(func, full_file_path, 0)]  # (function name, file path, depth)
                
                while queue:
                    current_func, current_file, depth = queue.pop(0)
                    
                    func_key = f"{current_file}:{current_func}"
                    if func_key in visited or depth > max_depth:
                        continue
                    
                    visited.add(func_key)
                    
                    # check if it's a public API
                    if current_func in public_apis:
                        related_apis.add(current_func)
                        print(f"[LSP FOUND] '{current_func}' is related (depth={depth})")
                        continue
                    
                    # find callers using LSP
                    callers = client.get_incoming_calls(current_file, current_func)
                    
                    for caller in callers:
                        # 호출자가 어느 파일에 있는지 찾기 (간단히 같은 파일로 가정)
                        queue.append((caller, current_file, depth + 1))
    
    finally:
        client.stop()
    
    return related_apis

def build_call_graph_simple(build_dir: str, changed_functions: Dict[str, Set[str]], 
                           public_apis: Set[str], max_depth: int = 3) -> Set[str]:
    """
    간단한 grep 기반 call graph 분석 (fallback)
    
    Args:
        build_dir: Path to the commit-specific build directory
        changed_functions: Dict mapping file paths to sets of changed function names
        public_apis: Set of known public API function names
        max_depth: Maximum call chain depth to explore
    """
    related_apis = set()
    visited = set()
    
    for file_path, functions in changed_functions.items():
        for func in functions:
            queue = [(func, 0)]
            
            while queue:
                current_func, depth = queue.pop(0)
                
                if current_func in visited or depth > max_depth:
                    continue
                    
                visited.add(current_func)
                
                if current_func in public_apis:
                    related_apis.add(current_func)
                    print(f"[GREP FOUND] '{current_func}' is related (depth={depth})")
                    continue
                
                # grep으로 호출자 찾기
                try:
                    result = subprocess.run(
                        ['grep', '-r', '-n', f'{current_func}(', build_dir, 
                         '--include=*.c', '--include=*.cpp', '--include=*.h'],
                        capture_output=True, text=True, timeout=10
                    )
                    
                    for line in result.stdout.split('\n'):
                        if ':' in line and current_func in line:
                            # 간단한 함수명 추출 시도
                            pass
                except Exception:
                    pass
    
    return related_apis
