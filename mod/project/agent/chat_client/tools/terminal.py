from . import register_tool
from .base import _xml_response
import shlex
import threading
import subprocess
import time
import uuid
import os
import re
from typing import Dict, Tuple, List

# 危险命令黑名单模式
DANGEROUS_COMMAND_PATTERNS = [
    r'rm\s+-rf\s+/$',  # rm -rf /
    r'rm\s+-rf\s+/\*',  # rm -rf /*
    r'rm\s+-rf\s+~',  # rm -rf ~
    r'rm\s+-rf\s+/www/server',  # 保护面板
    r'rm\s+-rf\s+/etc',  # 删除系统配置
    r'rm\s+-rf\s+/boot',  # 删除启动文件
    r'dd\s+if=',  # dd 磁盘操作
    r'mkfs',  # 格式化
    r'>\s*/dev/sd[a-z]',  # 直接写入磁盘
    r'>\s*/dev/nvme',  # 直接写入NVMe
    r'>\s*/etc/passwd',  # 覆盖用户数据库
    r'>\s*/etc/shadow',  # 覆盖密码文件
    r'chmod\s+777\s+/',  # 修改根目录权限
    r'chown\s+.*\s+/\s*$',  # 修改根目录所有者
    r'shutdown',  # 关机
    r'reboot',  # 重启
    r'halt',  # 停机
    r'poweroff',  # 关电
    r'init\s+0',  # 关机
    r'init\s+6',  # 重启
    r':\(\)\s*\{',  # Fork bomb
    r'curl.*\|\s*(bash|sh|python|perl)',  # 远程执行
    r'wget.*\|\s*(bash|sh|python|perl)',  # 远程执行
    r'base64.*\|\s*(bash|sh)',  # base64 解码执行
    r'iptables\s+-F',  # 清空防火墙规则
    r'\bnc\s+(-e|--exec)',  # 反弹 shell
    r'eval\s+',  # eval 执行
    r'exec\s+',  # exec 执行
]


def _protect_substitutions(command: str) -> tuple:
    """将 $(...) 和 `...` 替换为占位符, 防止 shlex 拆分命令替换内部内容。
    支持嵌套 $(): 循环替换直到稳定, 由内向外逐层处理。
    """
    replacements: List[str] = []

    def _replace(m):
        idx = len(replacements)
        replacements.append(m.group(0))
        return f'__SUBST_{idx}__'

    # 先替换反引号
    result = re.sub(r'`[^`]*`', _replace, command)
    # 循环替换 $() 直到稳定, 处理嵌套 $(echo $(cmd))
    prev = None
    while prev != result:
        prev = result
        result = re.sub(r'\$\([^()]*\)', _replace, result)
    return result, replacements


def _restore_substitutions(text: str, replacements: List[str]) -> str:
    """将占位符还原为原始的 $(...) 和 `...` 内容。"""
    for i, orig in enumerate(replacements):
        text = text.replace(f'__SUBST_{i}__', orig)
    return text


def _tokenize_command(command: str) -> list:
    """
    使用 shlex 分词命令, 正确处理所有 shell 引号规则。
    仅将 ; & | 视为标点 (用于识别 && || ; 分隔符),
    不拆分 > < ( ) 等重定向和子 shell 符号, 保持 2>/dev/null 等原样。
    """
    try:
        lex = shlex.shlex(command, punctuation_chars=';&|')
        lex.whitespace_split = True
        return list(lex)
    except ValueError:
        # 引号不匹配等异常, 降级为不拆分
        return [command.strip()] if command.strip() else []


_SPLIT_DELIMITERS = {';', '&&', '||'}


def _split_merged_command(command: str) -> list:
    """
    按逻辑控制符 (&&, ;, ||) 拆分命令, 跳过引号内和命令替换内的分隔符。
    基于 shlex 标准库, 覆盖单/双引号、反斜杠转义、ANSI-C 引用等场景。
    """
    protected, subs = _protect_substitutions(command)
    tokens = _tokenize_command(protected)

    # 找到顶层分隔符位置
    delim_indices = [i for i, t in enumerate(tokens) if t.strip() in _SPLIT_DELIMITERS]
    if not delim_indices:
        return [command.strip()] if command.strip() else []

    # 按分隔符位置切分 token 组, 每组合并为子命令字符串
    parts = []
    prev = 0
    for di in delim_indices:
        group = tokens[prev:di]
        if group:
            cmd = ' '.join(group)
            cmd = _restore_substitutions(cmd, subs)
            parts.append(cmd.strip())
        prev = di + 1
    # 末尾段
    tail = tokens[prev:]
    if tail:
        cmd = ' '.join(tail)
        cmd = _restore_substitutions(cmd, subs)
        parts.append(cmd.strip())

    return [p for p in parts if p]


def _split_merged_command_with_delims(command: str) -> list:
    """
    拆分合并命令并保留原连接符。
    返回 [(cmd, delim), ...] 列表。例如: "cmd1 && cmd2 ; cmd3" -> [('cmd1', '&&'), ('cmd2', ';'), ('cmd3', '')]
    基于 shlex 标准库, 跳过引号内和命令替换内的分隔符。
    """
    protected, subs = _protect_substitutions(command)
    tokens = _tokenize_command(protected)

    delim_indices = [(i, tokens[i].strip()) for i, t in enumerate(tokens) if t.strip() in _SPLIT_DELIMITERS]
    if not delim_indices:
        return [(command.strip(), "")] if command.strip() else []

    result = []
    prev = 0
    for di, delim in delim_indices:
        group = tokens[prev:di]
        if group:
            cmd = ' '.join(group)
            cmd = _restore_substitutions(cmd, subs)
            result.append((cmd.strip(), delim))
        prev = di + 1
    tail = tokens[prev:]
    if tail:
        cmd = ' '.join(tail)
        cmd = _restore_substitutions(cmd, subs)
        result.append((cmd.strip(), ""))

    return [(cmd, delim) for cmd, delim in result if cmd]


def _wrap_merged_command_with_markers(command: str) -> tuple:
    """
    包装合并命令，动态保留并应用原始连接符（&&, ||, ;），维持原 Shell 逻辑。
    返回 (wrapped_cmd, markers), markers 供 _parse_merged_output 使用。
    """
    parts = _split_merged_command_with_delims(command)
    wrapped_parts = []
    markers = []

    for i, (cmd, delim) in enumerate(parts):
        escaped_cmd = cmd.replace("'", "'\\''")
        start_m = f"===CMD_S_{i}==="
        end_m = f"===CMD_E_{i}==="
        markers.append((start_m, end_m))
        # 包装子命令; _rc 捕获退出码, exit $_rc 传播给外层 && / ||
        wrapped = (
            f'bash -c \'printf "{start_m}\\n"; {escaped_cmd}; _rc=$?; '
            f'printf "\\n{end_m}\\nRC=%s\\n" "$_rc"; exit $_rc\''
        )

        # 将原始连接符附带在包装好的命令之后
        if delim:
            wrapped_parts.append(f"{wrapped} {delim}")
        else:
            wrapped_parts.append(wrapped)

    return " ".join(wrapped_parts), markers


def _parse_merged_output(raw_output: str, command: str, markers: list = None) -> str:
    """
    解析合并命令的输出, 按 marker 分段展示每步结果。
    markers: _wrap_merged_command_with_markers 返回的 marker 列表,
            为 None 时回退到顺序编号匹配 (兼容旧调用)。
    """
    parts = _split_merged_command_with_delims(command)
    results = []

    def _get_markers(idx: int):
        if markers and idx < len(markers):
            return markers[idx]
        return f"===CMD_S_{idx}===", f"===CMD_E_{idx}==="

    for i in range(len(parts)):
        cmd_text = parts[i][0] if i < len(parts) else f"command_{i}"
        start_marker, end_marker = _get_markers(i)

        # 如果前一步被判定为 skipped，或者在 raw_output 中找不到当前步骤的 Marker
        start_idx = raw_output.find(start_marker)
        if start_idx == -1:
            is_previous_skipped = True
            results.append(f"[{i + 1}] {cmd_text}\nExit code: Skipped (Not Executed)\nOutput: -")
            continue

        output_start = start_idx + len(start_marker)
        end_idx = raw_output.find(end_marker, output_start)

        if end_idx == -1:
            cmd_output = raw_output[output_start:].strip()
            rc = -1
        else:
            cmd_output = raw_output[output_start:end_idx].strip()
            # 严格提取退出码: 跳过 printf 格式中的前导换行, 取第一个非空行匹配 ^RC=\d+$
            rc_part = raw_output[end_idx + len(end_marker):].lstrip('\n')
            first_nl = rc_part.find("\n")
            rc_line = rc_part[:first_nl].strip() if first_nl != -1 else rc_part.strip()
            m = re.match(r'^RC=(\d+)$', rc_line)
            rc = int(m.group(1)) if m else -1

        status = f"Exit code: {rc}"
        results.append(f"[{i + 1}] {cmd_text}\n{status}\n{cmd_output}")

    return "\n---\n".join(results)


def _is_dangerous_command(command: str) -> tuple:
    """检查命令是否危险, 返回 (is_dangerous, reason)。拆分合并命令后逐项检查。"""
    # 仅检查首词的模式 (eval, exec) - 避免误杀 grep eval 等合法命令
    _FIRST_TOKEN_PATTERNS = {r'eval\s+', r'exec\s+'}

    for part in _split_merged_command(command):
        # 提取命令首词
        tokens = part.split()
        first_token = tokens[0] if tokens else ""

        for pattern in DANGEROUS_COMMAND_PATTERNS:
            if pattern in _FIRST_TOKEN_PATTERNS:
                # eval/exec 只检查首词
                if re.search(pattern, first_token, re.IGNORECASE):
                    return True, f"Blocked by pattern: {pattern} (in: {part})"
            else:
                if re.search(pattern, part, re.IGNORECASE):
                    return True, f"Blocked by pattern: {pattern} (in: {part})"
    return False, None


# --- Command Manager for Non-blocking Commands ---
class CommandManager:
    # 已完成命令保留上限, 超出时自动清理最早的
    _MAX_DONE_COMMANDS = 50
    # 已完成命令最小存活时间 (秒)
    _DONE_MIN_AGE = 30

    def __init__(self):
        self.commands = {}
        self.lock = threading.Lock()

    def start_command(self, command: str, cwd: str) -> tuple:
        cmd_id = str(uuid.uuid4())

        shell_cmd = command
        if os.name == 'nt':
            shell_cmd = ["powershell", "-Command", command]

        try:
            process = subprocess.Popen(
                shell_cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                encoding='utf-8',
                errors='replace',
                shell=False if os.name == 'nt' else True
            )
        except Exception as e:
            return None, str(e)

        cmd_info = {
            "id": cmd_id,
            "process": process,
            "output": [],  # List of lines
            "status": "running",
            "start_time": time.time(),
            "cwd": cwd,
            "command": command
        }

        with self.lock:
            self.commands[cmd_id] = cmd_info

        # Start thread to read output
        t = threading.Thread(target=self._read_output, args=(cmd_id, process))
        t.daemon = True
        t.start()

        return cmd_id, None

    def _read_output(self, cmd_id, process):
        try:
            for line in iter(process.stdout.readline, ''):
                with self.lock:
                    if cmd_id in self.commands:
                        self.commands[cmd_id]["output"].append(line)
        except Exception:
            pass
        finally:
            try:
                process.stdout.close()
            except:
                pass

            return_code = process.wait()

            with self.lock:
                if cmd_id in self.commands:
                    # 不覆盖 stop_command 设置的 "stopped" 状态
                    if self.commands[cmd_id]["status"] != "stopped":
                        self.commands[cmd_id]["status"] = "done"
                    self.commands[cmd_id]["returncode"] = return_code
                    self._cleanup_done_commands()

    def _cleanup_done_commands(self):
        """清理超限的已完成命令, 释放内存。"""
        now = time.time()
        done_ids = [
            cid for cid, info in self.commands.items()
            if info["status"] == "done"
            and now - info.get("start_time", now) > self._DONE_MIN_AGE
        ]
        if len(done_ids) > self._MAX_DONE_COMMANDS:
            # 按时间排序, 清理最旧的
            done_ids.sort(key=lambda cid: self.commands[cid].get("start_time", 0))
            for cid in done_ids[:len(done_ids) - self._MAX_DONE_COMMANDS]:
                self.commands.pop(cid, None)

    def get_status(self, cmd_id: str, priority: str = "bottom", limit: int = 1000):
        with self.lock:
            if cmd_id not in self.commands:
                return None

            cmd = self.commands[cmd_id]
            output_lines = cmd["output"]

            if priority == "bottom":
                lines = output_lines[-limit:]
            else:
                lines = output_lines[:limit]

            return {
                "status": cmd["status"],
                "returncode": cmd.get("returncode"),
                "output": "".join(lines),
                "cwd": cmd["cwd"],
                "command": cmd["command"]
            }

    def stop_command(self, cmd_id: str):
        with self.lock:
            if cmd_id not in self.commands:
                return False

            cmd = self.commands[cmd_id]
            if cmd["status"] == "running":
                try:
                    cmd["process"].terminate()
                    cmd["status"] = "stopped"
                except:
                    pass
                return True
            return False


_CMD_MANAGER = CommandManager()


class BashSessionManager:
    """管理 Bash 会话的 subprocess 实例，支持跨调用保持 cwd 和环境变量。"""

    def __init__(self, session_timeout: int = 600):
        self._sessions: Dict[str, subprocess.Popen] = {}
        self._session_cwd: Dict[str, str] = {}
        self._last_used: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._exec_locks: Dict[str, threading.Lock] = {}  # per-session 执行锁
        self._session_timeout = session_timeout

    def create_session(self, session_id: str, cwd: str) -> bool:
        """创建新的 shell 会话"""
        with self._lock:
            if session_id in self._sessions:
                return False
            if os.name == 'nt':
                shell = ["powershell", "-NoExit", "-Command", "-"]
            else:
                shell = ["/bin/bash", "--norc", "--noprofile"]
            try:
                proc = subprocess.Popen(
                    shell, cwd=cwd,
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding='utf-8', errors='replace', bufsize=0,
                )
                self._sessions[session_id] = proc
                self._session_cwd[session_id] = cwd
                self._last_used[session_id] = time.time()
                self._exec_locks[session_id] = threading.Lock()
                return True
            except Exception:
                return False

    def execute_in_session(self, session_id: str, command: str, timeout: int = 120) -> Tuple[str, int]:
        """在已有会话中执行命令，返回 (output, returncode)。per-session 锁防止并发写入。"""
        with self._lock:
            proc = self._sessions.get(session_id)
            exec_lock = self._exec_locks.get(session_id)
            if not proc or proc.poll() is not None or not exec_lock:
                return "Session not found or expired.", -1
        self._last_used[session_id] = time.time()
        with exec_lock:  # per-session 锁: 防止多线程同时写入同一 stdin
            try:
                # 动态 delimiter: 含纳秒时间戳, 防止命令输出碰巧包含固定字符串
                delimiter = f"===BASH_EOF_{time.time_ns()}==="
                full_command = f"{command}; echo {delimiter}; echo $?"
                proc.stdin.write(full_command + "\n")
                proc.stdin.flush()
                output_lines = []
                deadline = time.time() + timeout
                found_delimiter = False
                while time.time() < deadline:
                    line = proc.stdout.readline()
                    if not line:
                        break
                    if delimiter in line:
                        found_delimiter = True
                        break
                    output_lines.append(line)
                returncode = -1
                if found_delimiter:
                    rc_line = proc.stdout.readline()
                    try:
                        returncode = int(rc_line.strip())
                    except (ValueError, TypeError):
                        pass
                return "".join(output_lines), returncode
            except Exception as e:
                return f"Error executing in session: {e}", -1

    def close_session(self, session_id: str) -> bool:
        """关闭指定会话"""
        with self._lock:
            proc = self._sessions.pop(session_id, None)
            self._session_cwd.pop(session_id, None)
            self._last_used.pop(session_id, None)
            self._exec_locks.pop(session_id, None)
        if proc:
            try:
                proc.stdin.write("exit\n")
                proc.stdin.flush()
                proc.stdin.close()
                proc.wait(timeout=5)
            except:
                proc.kill()
            return True
        return False

    def cleanup_expired(self):
        """清理超时会话"""
        now = time.time()
        with self._lock:
            expired = [sid for sid, t in self._last_used.items() if now - t > self._session_timeout]
        for sid in expired:
            self.close_session(sid)


_BASH_SESSION_MANAGER = BashSessionManager()


@register_tool(category="Agent", name_cn="Run Command", risk_level="high")
class RunCommand:
    """
    Execute shell commands. Supports merged command chains (e.g., `cd /tmp && ls && cat file.txt`).

    When to use:
    - Run terminal commands: git, npm, pip, systemctl, docker, etc.
    - Chain multiple dependent commands in one call using && or ; (output shows each step separately)
    - Maintain state across calls with session_id (keeps cwd and env variables)

    When NOT to use:
    - For file operations (reading/writing/editing/searching) — use the dedicated file tools instead
    - For interactive commands (top, nano, vi) — they will hang
    - For commands requiring sudo user input — use non-interactive flags (e.g., apt-get -y)

    Safety:
    - Dangerous commands are auto-blocked (rm -rf /, dd, mkfs, curl|bash, etc.)
    - Write-class commands (service restart/stop, file writes, custom script execution) are NOT auto-blocked but require user confirmation per Hard Red Lines — present the plan and wait for approval first.

    Command chaining examples:
    - `cd /www/wwwlogs && ls -la && tail -50 access.log` — 3 steps, single call
    - `echo "line1" && echo "line2" && echo "line3"` — all outputs individually labeled

    Args:
        command: Shell command to execute (supports && ; || chains)
        blocking: Wait for completion (default True). False returns immediately with a command_id for later polling.
        cwd: Working directory for the command
        timeout: Timeout in milliseconds (default 120000 = 2 min)
        session_id: Optional session ID to reuse the same subprocess (preserves cwd, env vars)
        description: Brief description of what this command does (for logging)
    """

    # 工具返回块中 <tool_name> 的来源; 子类 (如只读 ReadOnlyCommand) 覆盖即可复用执行逻辑
    _tool_name = "RunCommand"

    def execute(self, command: str, blocking: bool = True, cwd: str = None, timeout: int = 120000,
                session_id: str = None, description: str = None) -> str:
        BASH_MAX_RETURN_CHARS = 30000

        if not cwd:
            cwd = os.getcwd()

        # 危险命令检查
        is_dangerous, reason = _is_dangerous_command(command)
        if is_dangerous:
            return _xml_response(self._tool_name, "error", f"Dangerous command blocked. {reason}.")

        # 清理超时会话
        _BASH_SESSION_MANAGER.cleanup_expired()

        # 会话模式
        if session_id:
            return self._execute_session(command, session_id, cwd, timeout, description, BASH_MAX_RETURN_CHARS)

        # 无状态模式
        return self._execute_stateless(command, cwd, timeout, blocking, description, BASH_MAX_RETURN_CHARS)

    def _execute_stateless(self, command: str, cwd: str, timeout: int, blocking: bool,
                           description: str, max_chars: int) -> str:
        """无状态模式：每次执行独立 subprocess，合并命令注入动态分界符"""
        if not blocking:
            cmd_id, err = _CMD_MANAGER.start_command(command, cwd)
            if err:
                return _xml_response(self._tool_name, "error", err, max_chars=max_chars)

            result = (
                f"<terminal_id>new</terminal_id>\n"
                f"<terminal_cwd>{cwd}</terminal_cwd>\n"
                f"Note: Command ID is provided for you to check command status later.\n"
                f"<command_id>{cmd_id}</command_id>\n"
                f"The command is running, you need to call check_command_status tool to get more logs.\n"
            )
            return _xml_response(self._tool_name, "running", result, max_chars=max_chars)

        try:
            parts = _split_merged_command(command)
            is_merged = len(parts) > 1

            if is_merged:
                # 合并命令：注入动态分界符
                shell_cmd, markers = _wrap_merged_command_with_markers(command)
            else:
                shell_cmd = command
                markers = None

            if os.name == 'nt':
                shell_cmd = ["powershell", "-Command", shell_cmd]

            timeout_sec = timeout / 1000.0
            start_time = time.time()

            result = subprocess.run(
                shell_cmd, cwd=cwd, capture_output=True, text=True,
                encoding='utf-8', errors='replace',
                shell=False if os.name == 'nt' else True, timeout=timeout_sec
            )

            raw_output = result.stdout + result.stderr
            duration = time.time() - start_time

            if is_merged:
                output = _parse_merged_output(raw_output, command, markers)
            else:
                output = raw_output

            metadata = f"Exit Code: {result.returncode}\nDuration: {duration:.2f}s"
            final_output = f"{metadata}\n\n{output}"

            if description:
                final_output = f"Description: {description}\n\n{final_output}"

            return _xml_response(self._tool_name, "done", final_output, max_chars=max_chars)

        except subprocess.TimeoutExpired:
            return _xml_response(self._tool_name, "error", f"Command timed out after {timeout} ms", max_chars=max_chars)
        except Exception as e:
            return _xml_response(self._tool_name, "error", str(e), max_chars=max_chars)

    def _execute_session(self, command: str, session_id: str, cwd: str, timeout: int,
                         description: str, max_chars: int) -> str:
        """会话模式：复用已有 subprocess 实例，合并命令注入动态分界符"""
        if session_id not in _BASH_SESSION_MANAGER._sessions:
            if not _BASH_SESSION_MANAGER.create_session(session_id, cwd):
                return _xml_response(self._tool_name, "error", f"Failed to create session: {session_id}")

        parts = _split_merged_command(command)
        is_merged = len(parts) > 1

        if is_merged:
            exec_cmd, markers = _wrap_merged_command_with_markers(command)
        else:
            exec_cmd = command
            markers = None

        timeout_sec = timeout / 1000.0
        start_time = time.time()

        raw_output, returncode = _BASH_SESSION_MANAGER.execute_in_session(session_id, exec_cmd, int(timeout_sec))
        duration = time.time() - start_time

        if is_merged:
            output = _parse_merged_output(raw_output, command, markers)
        else:
            output = raw_output

        metadata = f"Exit Code: {returncode}\nDuration: {duration:.2f}s\nSession: {session_id}"
        final_output = f"{metadata}\n\n{output}"

        if description:
            final_output = f"Description: {description}\n\n{final_output}"

        return _xml_response(self._tool_name, "done", final_output, max_chars=max_chars)
