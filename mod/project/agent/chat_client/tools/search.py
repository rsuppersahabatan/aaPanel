import glob
import re
import os
from typing import List

# aaPanel 运行时依赖
os.chdir('/www/server/panel/')
import sys
sys.path.insert(0, 'class/')
sys.path.insert(0, '/www/server/panel/')
import public
from public import lang

try:
    from public.hook_import import hook_import
    hook_import()
except:
    pass

from . import register_tool
from .base import _xml_response


@register_tool(category="Agent", name_cn="Glob Find", risk_level="low")
def Glob(pattern: str, path: str = None) -> str:
    """
    Fast file pattern matching. Finds files matching glob patterns like "**/*.py" or "src/**/*.js".

    When to use:
    - Find files by name pattern or extension across a directory tree
    - Locate config files, source files, or log files by extension
    - Discover all files of a specific type (e.g., "*.conf", "*.log")

    When NOT to use:
    - To search file contents — use Grep Search instead
    - To list directory structure — use List Directory instead

    Args:
        pattern: The glob pattern to match (e.g., "*.conf", "**/*.py", "nginx/*")
        path: The directory to search in (absolute path). Defaults to /www/server/panel/

    Returns: file paths sorted by mtime, max 100 results. Truncated results include a hint.
    """
    if not path:
        path = os.getcwd()

    try:
        if not os.path.exists(path):
            return _xml_response("Glob", "error", f"Path not found: {path}")

        search_path = os.path.join(path, pattern)
        files = glob.glob(search_path, recursive=True)

        # Filter only files and sort by mtime (descending)
        file_stats = []
        for f in files:
            if os.path.isfile(f):
                try:
                    mtime = os.path.getmtime(f)
                    file_stats.append((f, mtime))
                except:
                    pass

        file_stats.sort(key=lambda x: x[1], reverse=True)

        limit = 100
        truncated = False
        if len(file_stats) > limit:
            file_stats = file_stats[:limit]
            truncated = True

        output = [f[0] for f in file_stats]

        if not output:
            return _xml_response("Glob", "done", "No files found")

        result = "\n".join(output)
        if truncated:
            result += f"\n\n(Results are truncated: showing first {limit} results. Consider using a more specific path or pattern.)"

        return _xml_response("Glob", "done", result)
    except Exception as e:
        return _xml_response("Glob", "error", str(e))


@register_tool(category="Agent", name_cn="Grep Search", risk_level="low")
def Grep(pattern: str, include: str = None, path: str = None, **kwargs) -> str:
    r"""
    Search file contents using regular expressions. Returns matching lines with file paths and line numbers.

    When to use:
    - Find where a specific function, variable, or configuration is defined/used
    - Search for error messages, log patterns, or specific text across multiple files
    - Locate code by content rather than filename

    When NOT to use:
    - To find files by name pattern — use Glob Find instead
    - To count exact matches or complex analysis — use RunCommand with `rg` (ripgrep)

    Args:
        pattern: The regex pattern to search for (e.g., "def get_sites", "error.*timeout")
        include: File glob filter (e.g., "**/*.py" for recursive, "*.conf" for top-level only). Defaults to all files.
        path: The directory to search in (absolute path). Defaults to /www/server/panel/

    Returns: matches grouped by file with line numbers, max 100 matches. Truncated results include a hint.
    """
    if not path:
        path = os.getcwd()

    try:
        import glob as glob_module

        # 1. Find files
        files_to_search = []
        if os.path.isfile(path):
            files_to_search = [path]
        else:
            search_glob = include if include else "**/*"
            candidates = glob_module.glob(os.path.join(path, search_glob), recursive=True)
            files_to_search = [f for f in candidates if os.path.isfile(f)]

        regex = re.compile(pattern)
        matches = []
        MAX_LINE_LENGTH = 2000

        for file_path in files_to_search:
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
                    try:
                        mtime = os.path.getmtime(file_path)
                    except:
                        mtime = 0

                    for i, line in enumerate(lines):
                        if regex.search(line):
                            matches.append({
                                "path": file_path,
                                "lineNum": i + 1,
                                "lineText": line.rstrip(),
                                "mtime": mtime
                            })
            except Exception:
                continue

        # Sort by mtime desc
        matches.sort(key=lambda x: x["mtime"], reverse=True)

        limit = 100
        truncated = len(matches) > limit
        final_matches = matches[:limit] if truncated else matches

        if not final_matches:
            return _xml_response("Grep", "done", "No files found")

        output_lines = [f"Found {len(matches)} matches{f' (showing first {limit})' if truncated else ''}"]

        current_file = ""
        for match in final_matches:
            if current_file != match["path"]:
                if current_file != "":
                    output_lines.append("")
                current_file = match["path"]
                output_lines.append(f"{match['path']}:")

            line_text = match["lineText"]
            if len(line_text) > MAX_LINE_LENGTH:
                line_text = line_text[:MAX_LINE_LENGTH] + "..."
            output_lines.append(f"  Line {match['lineNum']}: {line_text}")

        if truncated:
            output_lines.append("")
            output_lines.append(
                f"(Results truncated: showing {limit} of {len(matches)} matches. Consider using a more specific path or pattern.)")

        return _xml_response("Grep", "done", "\n".join(output_lines))
    except Exception as e:
        return _xml_response("Grep", "error", str(e))


@register_tool(category="Agent", name_cn="List Directory", risk_level="low")
def LS(path: str = None, ignore: List[str] = None) -> str:
    """
    Browse directory structure. Lists files and subdirectories with a tree-like view, auto-ignoring common noise directories (node_modules, .git, __pycache__, etc).

    When to use:
    - Explore unknown directory structures or understand project layout
    - Check what files exist in a specific directory
    - Quick overview of project structure

    When NOT to use:
    - To find files by pattern — use Glob Find instead
    - To search file contents — use Grep Search instead

    Args:
        path: The absolute path to list. Defaults to /www/server/panel/
        ignore: Additional glob patterns to exclude (e.g., ["*.log", "temp/*"])

    Returns: tree-like view, 2 levels deep, max 100 entries per directory. Auto-ignores node_modules, .git, __pycache__, etc.
    """
    if not path:
        path = os.getcwd()

    try:
        if not os.path.exists(path):
            return _xml_response("LS", "error", "Path not found")

        DEFAULT_IGNORE = [
            "node_modules", "__pycache__", ".git", "dist", "build", "target",
            "vendor", "bin", "obj", ".idea", ".vscode", ".zig-cache", "zig-out",
            "coverage", "tmp", "temp", ".cache", "logs",
            ".venv", "venv", "env"
        ]

        ignore_patterns = DEFAULT_IGNORE + (ignore if ignore else [])

        LIMIT = 100

        def should_ignore(name):
            return name in ignore_patterns or any(glob.fnmatch.fnmatch(name, p) for p in ignore_patterns)  # noqa

        try:
            entries = os.listdir(path)
        except PermissionError:
            return _xml_response("LS", "error", f"Permission denied: {path}")

        dirs = []
        files = []
        for entry in entries:
            if should_ignore(entry):
                continue
            full_path = os.path.join(path, entry)
            if os.path.isdir(full_path):
                dirs.append(entry)
            else:
                files.append(entry)

        dirs.sort()
        files.sort()

        output_lines = [f"{path}/"]

        for d in dirs:
            subdir_path = os.path.join(path, d)
            output_lines.append(f"  {d}/")

            try:
                sub_entries = os.listdir(subdir_path)
            except PermissionError:
                continue

            sub_dirs = []
            sub_files = []
            for entry in sub_entries:
                if should_ignore(entry):
                    continue
                entry_path = os.path.join(subdir_path, entry)
                if os.path.isdir(entry_path):
                    sub_dirs.append(entry)
                else:
                    sub_files.append(entry)

            sub_dirs.sort()
            sub_files.sort()

            count = 0
            truncated = False
            for sub_d in sub_dirs:
                if count >= LIMIT:
                    truncated = True
                    break
                output_lines.append(f"    {sub_d}/")
                count += 1

            for sub_f in sub_files:
                if count >= LIMIT:
                    truncated = True
                    break
                output_lines.append(f"    {sub_f}")
                count += 1

            if truncated:
                output_lines.append(
                    f"    ... ({lang('Showing')} {LIMIT} {lang('items in current directory, use LS tool for more')})")

        for f in files:
            output_lines.append(f"  {f}")

        return _xml_response("LS", "done", "\n".join(output_lines))
    except Exception as e:
        return _xml_response("LS", "error", str(e))