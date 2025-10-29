"""
Harness generator powered by GPT (with offline fallback).
- Gathers function declarations/definitions for public APIs
- Builds a clear prompt and asks an LLM to synthesize a minimal fuzz harness
- Writes per-API harness files
- Validates harness compilation with AFL (up to 3 retries with error feedback)

Requirements:
- openai>=1.0.0 in requirements.txt
- Set OPENAI_API_KEY in env (optional; if missing, uses offline stub)
"""
import os
import re
import textwrap
import subprocess
from typing import Dict, Optional, Set, Tuple, List

try:
    from openai import OpenAI  # type: ignore
    _HAS_OPENAI = True
except Exception:
    _HAS_OPENAI = False

# -----------------------------
# Code search and extraction
# -----------------------------

def _iter_source_files(root: str) -> List[str]:
    exts = {'.c', '.cc', '.cpp', '.h', '.hpp'}
    out = []
    for dirpath, _, files in os.walk(root):
        for fn in files:
            if os.path.splitext(fn)[1] in exts:
                out.append(os.path.join(dirpath, fn))
    return out

_DEF_SIG_RE_TMPL = r"\b{fname}\s*\("


def find_function_declaration(repo_path: str, func: str) -> Optional[Tuple[str, str]]:
    """Return (file_path, declaration_line_or_block) from headers if found."""
    include_dir = os.path.join(repo_path, 'include')
    search_roots = [include_dir, repo_path]
    sig_re = re.compile(_DEF_SIG_RE_TMPL.format(fname=re.escape(func)))
    for root in search_roots:
        if not os.path.isdir(root):
            continue
        for fp in _iter_source_files(root):
            if not fp.endswith(('.h', '.hpp')):
                continue
            try:
                with open(fp, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                # naive: find first line containing func( ... );
                for m in sig_re.finditer(content):
                    # get the line around the match up to semicolon
                    start = content.rfind('\n', 0, m.start()) + 1
                    semi = content.find(';', m.end())
                    if semi == -1:
                        continue
                    decl = content[start:semi + 1]
                    return (fp, decl.strip())
            except Exception:
                continue
    return None


def find_function_definition(repo_path: str, func: str) -> Optional[Tuple[str, str]]:
    """Return (file_path, definition_block) by naive brace matching in source files."""
    sig_re = re.compile(_DEF_SIG_RE_TMPL.format(fname=re.escape(func)))
    for fp in _iter_source_files(repo_path):
        if fp.endswith(('.h', '.hpp')):
            continue
        try:
            with open(fp, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            m = sig_re.search(content)
            if not m:
                continue
            # find opening brace for the function body
            brace_open = content.find('{', m.end())
            if brace_open == -1:
                # maybe inline or prototype only; fallback: take 10 lines
                start = content.rfind('\n', 0, m.start()) + 1
                end = content.find('\n', m.end())
                block = content[start:end if end != -1 else len(content)]
                return (fp, block.strip())
            depth = 1
            i = brace_open + 1
            while i < len(content) and depth > 0:
                if content[i] == '{':
                    depth += 1
                elif content[i] == '}':
                    depth -= 1
                i += 1
            block = content[m.start():i]
            return (fp, block.strip())
        except Exception:
            continue
    return None

# -----------------------------
# Prompting and generation
# -----------------------------

_DEFAULT_SYSTEM = (
    "You are an expert C/C++ engineer generating minimal, buildable fuzz harnesses. "
    "Prefer deterministic, safe, compilable code. If arguments are unknown, stub with reasonable defaults and TODOs."
)


def _build_prompt(api: str, decl: Optional[str], definition_snippet: Optional[str], lib_name: str) -> str:
    parts = [
        f"Target library: {lib_name}",
        f"Public API to exercise: {api}",
    ]
    if decl:
        parts.append("Declaration:\n" + decl)
    if definition_snippet:
        # truncate very long snippets
        snippet = definition_snippet
        if len(snippet) > 4000:
            snippet = snippet[:4000] + "\n/* ...snip... */\n"
        parts.append("Relevant implementation snippet:\n" + snippet)
    
    # Include path guidance
    include_hint = ""
    if lib_name == "libxml2":
        include_hint = (
            "Important: Use angle brackets for libxml2 headers, e.g., #include <libxml/parser.h>. "
            "The harness will be compiled with -I flag pointing to afl_libs/libxml2/include."
        )
    
    parts.append(
        textwrap.dedent(
            f"""
            Please write a single C harness file that:
            - Includes the correct headers for {api} (use angle brackets, not quotes)
            - {include_hint}
            - MUST initialize the library properly (e.g., xmlInitParser() for libxml2)
            - MUST handle null pointers and errors safely (check return values)
            - Invokes {api} with VALID, non-null arguments (create proper objects/contexts first)
            - Uses simple, deterministic inputs (no stdin/AFL input for now - keep it runnable)
            - Cleans up resources properly (free memory, close handles)
            - Returns 0 on success
            
            CRITICAL SAFETY RULES:
            - Never pass NULL to any API function
            - Always initialize library-specific contexts before using APIs
            - Check all return values and handle errors
            - Use stack-allocated or simple heap data when possible
            - The harness MUST run without crashing even with no input files
            
            Constraints:
            - No external deps beyond standard C and the library's public headers
            - Must compile as a standalone .c file
            - Use angle brackets for library headers: #include <libxml/...> not #include "libxml/..."
            Output: Only the C code. No markdown, no explanations.
            """
        ).strip()
    )
    return "\n\n".join(parts)


def _call_openai(prompt: str, model: str = "gpt-4o-mini") -> Optional[str]:
    if not _HAS_OPENAI:
        return None
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        return None
    try:
        client = OpenAI()
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _DEFAULT_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        content = resp.choices[0].message.content if resp.choices else None
        if content:
            # Strip markdown code fences
            content = _strip_markdown_fences(content)
        return content
    except Exception as e:
        print(f"[WARN] OpenAI call failed: {e}")
        return None


def _strip_markdown_fences(code: str) -> str:
    """Remove markdown code block fences like ```c ... ``` or ``` ... ```"""
    code = code.strip()
    # Pattern: ```c or ```cpp or ``` at start
    if code.startswith('```'):
        lines = code.split('\n')
        # Remove first line if it's a fence
        if lines[0].strip().startswith('```'):
            lines = lines[1:]
        # Remove last line if it's a fence
        if lines and lines[-1].strip() == '```':
            lines = lines[:-1]
        code = '\n'.join(lines)
    return code.strip()


def _try_compile_harness(harness_path: str, lib_name: str, repo_path: str, api: str) -> Tuple[bool, str]:
    """
    Attempt to compile the harness with AFL.
    Returns (success: bool, error_message: str)
    """
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    include_dir = os.path.join(project_root, 'afl_libs', lib_name, 'include')
    lib_dir = os.path.join(project_root, 'afl_libs', lib_name, '.libs')
    
    # Sanitize lib name for -l flag (e.g., libxml2 -> xml2)
    lib_flag = lib_name.replace('lib', '', 1) if lib_name.startswith('lib') else lib_name
    
    out_bin = harness_path.replace('.c', '')
    
    # Try afl-clang-fast with ASAN, fallback to clang with ASAN
    compilers = [
        ['afl-clang-fast', '-fsanitize=address'],
        ['clang', '-fsanitize=address'],
    ]
    
    for compiler_config in compilers:
        compiler = compiler_config[0]
        cmd = [
            *compiler_config,
            '-I', include_dir,
            harness_path,
            '-L', lib_dir,
            f'-l{lib_flag}',
            '-o', out_bin,
            '-Wno-deprecated-declarations',  # suppress deprecated warnings
            '-Wno-unused-command-line-argument',  # suppress irrelevant warnings
        ]
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=os.path.dirname(harness_path)
            )
            
            # Success if return code is 0 (warnings are OK)
            if result.returncode == 0:
                print(f"[BUILD OK] {compiler}: {os.path.basename(harness_path)}")
                return (True, "")
            else:
                err = result.stderr.strip()
                # Only treat as real error if returncode != 0
                if compiler == compilers[-1][0]:  # last compiler attempt
                    return (False, err)
        except FileNotFoundError:
            if compiler == compilers[-1][0]:
                return (False, f"{compiler} not found in PATH")
            continue
        except Exception as e:
            if compiler == compilers[-1][0]:
                return (False, str(e))
            continue
    
    return (False, "All compilers failed")


def _fix_harness_with_feedback(api: str, original_prompt: str, code: str, error: str, model: str) -> Optional[str]:
    """Ask GPT to fix the harness based on compilation error."""
    if not _HAS_OPENAI or not os.getenv('OPENAI_API_KEY'):
        return None
    
    fix_prompt = (
        f"{original_prompt}\n\n"
        "The previous harness failed to compile with the following error:\n\n"
        f"```\n{error}\n```\n\n"
        "Please fix the harness code to address this compilation error. "
        "Output: Only the corrected C code. No markdown, no explanations."
    )
    
    try:
        client = OpenAI()
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _DEFAULT_SYSTEM},
                {"role": "user", "content": fix_prompt},
            ],
            temperature=0.2,
        )
        content = resp.choices[0].message.content if resp.choices else None
        if content:
            # Strip markdown code fences
            content = _strip_markdown_fences(content)
        return content
    except Exception as e:
        print(f"[WARN] OpenAI fix attempt failed: {e}")
        return None


def generate_harness_for_apis(repo_path: str, lib_name: str, api_names: Set[str], out_dir: str,
                              model: str = "gpt-4o-mini", max_retries: int = 3) -> Dict[str, str]:
    """
    For each API, collect declaration/definition and ask GPT to synthesize a harness.
    Validates compilation with AFL and retries up to max_retries times if build fails.
    Returns a map: api_name -> output_file_path
    """
    os.makedirs(out_dir, exist_ok=True)
    outputs: Dict[str, str] = {}

    for api in sorted(api_names):
        decl = find_function_declaration(repo_path, api)
        defi = find_function_definition(repo_path, api)
        decl_txt = decl[1] if decl else None
        def_txt = defi[1] if defi else None

        prompt = _build_prompt(api, decl_txt, def_txt, lib_name)
        generated = _call_openai(prompt, model=model)

        if not generated:
            # Offline fallback stub
            header_hint = "#include <libxml/parser.h>\n" if lib_name == 'libxml2' else ""
            init_hint = "    xmlInitParser();\n" if lib_name == 'libxml2' else ""
            cleanup_hint = "    xmlCleanupParser();\n" if lib_name == 'libxml2' else ""
            
            generated = (
                f"/* Offline stub harness for {lib_name}:{api}. Set OPENAI_API_KEY to enable LLM generation. */\n"
                + header_hint +
                "#include <stdio.h>\n"
                "#include <stdlib.h>\n\n"
                "int main(int argc, char **argv) {\n"
                + init_hint +
                f"    // TODO: include proper headers and call {api} with valid, non-null arguments.\n"
                f"    // IMPORTANT: Initialize library context and check for null before calling {api}\n"
                f"    // Compile with: afl-clang-fast -fsanitize=address -I../../afl_libs/{lib_name}/include harness_{api}.c -L../../afl_libs/{lib_name}/.libs -l{lib_name.replace('lib', '')} -o harness_{api}\n"
                "    (void)argc; (void)argv;\n"
                + cleanup_hint +
                "    return 0;\n"
                "}\n"
            )

        # Sanitize filename
        safe_api = re.sub(r"[^A-Za-z0-9_]+", "_", api)
        out_file = os.path.join(out_dir, f"harness_{safe_api}.c")
        
        # Write and validate with retries
        build_success = False
        for attempt in range(max_retries):
            try:
                with open(out_file, 'w', encoding='utf-8') as f:
                    f.write(generated)
                print(f"[HARNESS] Wrote {out_file} (attempt {attempt + 1}/{max_retries})")
                
                # Try to compile
                success, error = _try_compile_harness(out_file, lib_name, repo_path, api)
                
                if success:
                    build_success = True
                    outputs[api] = out_file
                    break
                else:
                    print(f"[BUILD FAIL] Attempt {attempt + 1}/{max_retries} failed: {error[:200]}")
                    
                    # Try to fix with GPT feedback (only if API key available)
                    if attempt < max_retries - 1:
                        fixed = _fix_harness_with_feedback(api, prompt, generated, error, model)
                        if fixed:
                            generated = fixed
                            print(f"[RETRY] GPT provided fix for {api}")
                        else:
                            print(f"[RETRY] No GPT fix available, keeping original code")
                            
            except Exception as e:
                print(f"[ERROR] Failed to write/build harness for {api}: {e}")
                break
        
        if not build_success:
            print(f"[FINAL] Harness for {api} did not compile after {max_retries} attempts")

    return outputs


# Backward-compatible simple API

def generate_harness_with_gpt(api_names: Set[str], model: str = 'gpt-4o-mini') -> str:
    """Return a concatenated harness stub for quick preview (legacy interface)."""
    code = '#include <stdio.h>\n\nint main() {\n'
    for api in api_names:
        code += f'    // TODO: call {api} with sample arguments\n'
    code += '    return 0;\n}\n'
    return code

if __name__ == "__main__":
    pass
