from . import register_tool
from .base import _xml_response
from .terminal import (
    RunCommand, _is_dangerous_command, _split_merged_command,
    _tokenize_command, _protect_substitutions, _restore_substitutions,
)
import re

# shell 元字符黑名单: $(...) 和反引号不再直接拒 — 由 _check_substitutions 递归校验内部命令.
# 堵 进程替换 heredoc 输入重定向 后台执行符 换行注入 — 父类 shell=True 下会被 bash 解释执行.
_SHELL_METACHAR_RE = re.compile(
    r'[<>]\('            # <( / >( 进程替换
    r'|<<<'              # here-string
    r'|<<'               # heredoc
    r'|<'                # < 输入重定向
    r'|(?<!&)&(?!&)'     # 单 & 后台执行(不误杀 &&)
    r'|\n|\r'            # 换行符(解析器差异: shlex 当空白, shell 当命令分隔)
)

# 只读命令白名单(首词): 子代理 OS 层诊断回退通道 — panel 专用只读工具未覆盖的状态/进程/端口/日志/
# 配置/网络/资源/语法校验. 默认拒绝.
# 不纳入: 交互式 pager(less/more hang)、非交互不存在的 alias(ll)、带参即写(mount/ip/ifconfig)、
#         多执行通道(mysql→MysqlQuery, env→printenv).
_READONLY_COMMANDS = {
    # 文本与文件查看
    'cat', 'head', 'tail', 'wc', 'grep', 'egrep', 'fgrep', 'rg', 'ack',
    'find', 'ls', 'stat', 'file', 'tree', 'du', 'df', 'diff',
    'md5sum', 'sha256sum', 'od', 'hexdump',
    # 路径工具(管道常用)
    'which', 'whereis', 'readlink', 'realpath', 'basename', 'dirname',
    # 进程与系统资源(top 需 -b 批处理; 裸交互 top 由 timeout 兜底)
    'ps', 'top', 'free', 'uptime', 'uname', 'w', 'who', 'id', 'whoami',
    'vmstat', 'iostat', 'sar',
    # 网络(无 ip/ifconfig — 写在 tokens[2], 用 ss/netstat/lsof 查连接端口)
    'ss', 'netstat', 'lsof', 'dig', 'nslookup', 'host', 'ping', 'traceroute', 'curl',
    # 系统与服务只读
    'systemctl', 'journalctl', 'dmesg', 'lsblk', 'lsmod', 'lspci', 'lsusb',
    'findmnt', 'getenforce', 'sestatus', 'printenv', 'echo', 'date',
    'hostname', 'hostnamectl', 'timedatectl', 'lsb_release', 'getent', 'last',
    # 应用层(只读形态由 _READONLY_FORMS 严格限定; 默认拒绝未列出的子命令/选项)
    'nginx', 'php', 'redis-cli', 'crontab', 'openssl', 'docker',
}

# 反向只读形态: 首词 -> 允许的只读子命令/选项(默认拒绝). 三种形态:
#   subs     : tokens[1] ∈ subs(docker/redis-cli/crontab/openssl); docker 还支持 obj 二级
#   subs_opts: 跳过所有 - 开头选项 token, 取第一个非选项 token ∈ subs; 选项必须 ∈ opts(systemctl/timedatectl/hostnamectl)
#   opts     : 所有 - 开头 token ∈ opts(curl/nginx/php/date/dmesg/hostname/ss); 组合短选项(-sL)拆解逐一检查
#   no_flags : 见到即拒(redis-cli 远程, openssl 写文件)
#   no_args  : 禁止裸参(hostname — 裸参 = 设置主机名)
_READONLY_FORMS = {
    # -- docker: subs 型(含 obj 二级) --
    'docker': {
        'subs': {'ps', 'inspect', 'logs', 'stats', 'version', 'images', 'top',
                 'port', 'history', 'diff', 'info', 'search'},
        'obj': {'network': {'ls', 'inspect'},
                'volume': {'ls', 'inspect'},
                'image': {'ls', 'inspect', 'history'},
                'container': {'ls', 'inspect', 'top', 'logs', 'stats', 'diff', 'port'},
                'system': {'df', 'info', 'events'}},
    },
    # -- redis-cli: subs 型(大写归一, CONFIG 仅 GET) --
    'redis-cli': {
        'subs': {'GET', 'MGET', 'EXISTS', 'TYPE', 'KEYS', 'SCAN', 'TTL', 'PTTL',
                 'DBSIZE', 'INFO', 'TIME', 'ECHO', 'COMMAND', 'OBJECT', 'CONFIG'},
        'no_flags': {'-h', '-a', '-p', '-u', '--rdb', '--pipe', '--cluster'},
    },
    # -- crontab: subs 型(仅 -l) --
    'crontab': {
        'subs': {'-l', '--list'},
    },
    # -- openssl: subs 型 + no_flags --
    'openssl': {
        'subs': {'x509', 's_client', 'verify', 'version', 's_time', 'pkcs7', 'ec',
                 'pkey', 'speed', 'ciphers', 'list', 'errstr'},
        'no_flags': {'-out', '-keyout', '-CAserial', '-passout', '-signkey'},
    },
    # -- systemctl: subs_opts 型(跳过前置选项, 取实际子命令) --
    'systemctl': {
        'subs_opts': True,
        'opts': {'--no-ask-password', '--no-pager', '--no-legend', '--quiet', '-q',
                 '--system', '--user', '--global', '--failed', '--all', '-a',
                 '--full', '-l', '--plain', '--host', '-H', '--machine', '-M',
                 '--property', '-p', '--state', '--type', '-t', '--output', '-o'},
        'arg_opts': {'--host', '-H', '--machine', '-M', '--property', '-p',
                     '--state', '--type', '-t', '--output', '-o'},
        'subs': {'status', 'is-active', 'is-enabled', 'is-failed', 'list-units',
                 'list-unit-files', 'list-timers', 'list-jobs', 'list-dependencies',
                 'list-sockets', 'list-machines', 'show', 'cat', 'help', 'get-default',
                 'is-system-running', 'list-dependencies'},
    },
    # -- timedatectl: subs_opts 型 --
    'timedatectl': {
        'subs_opts': True,
        'opts': {'--no-ask-password', '--adjust-system-clock', '--host', '-H',
                 '--machine', '-M', '--help', '--version'},
        'arg_opts': {'--host', '-H', '--machine', '-M'},
        'subs': {'status', 'show', 'list-timezones', 'timesync-status', 'ntp-servers'},
    },
    # -- hostnamectl: subs_opts 型(仅 status 只读) --
    'hostnamectl': {
        'subs_opts': True,
        'opts': {'--no-ask-password', '--static', '--transient', '--pretty',
                 '--host', '-H', '--machine', '-M', '--help', '--version'},
        'arg_opts': {'--host', '-H', '--machine', '-M'},
        'subs': {'status'},
    },
    # -- curl: opts 型(裸 URL 放行) --
    'curl': {
        'opts': {'-I', '-i', '-s', '-S', '-L', '-v', '-k', '-A', '-m', '-H',
                 '--head', '--silent', '--location', '--max-time', '--insecure',
                 '--compressed', '--connect-timeout'},
    },
    # -- nginx: opts 型(必须至少一个只读 flag; 裸跑 = 启动服务, 拒) --
    'nginx': {
        'opts': {'-t', '-T', '-V', '-v', '-q'},
        'require_opt': True,
    },
    # -- php: opts 型(必须至少一个只读 flag; 裸跑 = REPL, 拒) --
    'php': {
        'opts': {'-l', '-v', '-m', '-i', '--ini', '--rf', '--rc', '--re', '--ri'},
        'require_opt': True,
    },
    # -- date: opts 型, 排除 -s/--set; 裸 date = 显示当前时间(放行) --
    'date': {
        'opts': {'-u', '-R', '-I', '-r', '-d', '--utc', '--rfc-2822', '--rfc-3339',
                 '--iso-8601', '--date', '--reference', '--help', '--version'},
    },
    # -- dmesg: opts 型, 排除 -c/-C/-n/-D/-w --
    'dmesg': {
        'opts': {'-H', '-k', '-l', '-u', '-T', '-t', '-P', '-p', '-e', '-x',
                 '--human', '--kernel', '--level', '--userspace', '--ctime',
                 '--notime', '--force-prefix', '--reltime', '--since', '--until',
                 '--decode', '--help', '--version'},
    },
    # -- hostname: opts 型, 禁止裸参(hostname NEWS = 设置主机名); 无参 = 显示(放行) --
    'hostname': {
        'opts': {'-A', '-d', '-f', '-i', '-I', '-s', '--all-fqdns', '--domain',
                 '--fqdn', '--ip-address', '--all-ip-addresses', '--short',
                 '--help', '--version'},
        'no_args': True,  # 裸参 = 设置主机名(写)
    },
    # -- ss: opts 型, 排除 -K/--kill/-D/--dump --
    'ss': {
        'opts': {'-a', '-l', '-p', '-t', '-u', '-w', '-x', '-4', '-6', '-0', '-n',
                 '-r', '-o', '-e', '-m', '-i', '-s', '-b', '-Z', '-z', '-d', '-f',
                 '-A', '-N', '-O', '--all', '--listening', '--tcp', '--udp', '--raw',
                 '--unix', '--packet', '--dccp', '--sctp', '--vsock', '--processes',
                 '--numeric', '--resolve', '--options', '--extended', '--memory',
                 '--info', '--summary', '--bpf', '--context', '--help', '--version'},
    },
}

# 正向写子命令(全已移入 _READONLY_FORMS; 保留空 dict 供未来扩展, 不加新条目)
_WRITE_SUBCOMMANDS = {}

# 写操作符: 输出重定向/追加(>/dev/null 除外), 管道到解释器/tee/&, find 写参数(位置不固定, 走正则)
_WRITE_OPERATOR_RE = re.compile(
    r'>>?(?!\s*/dev/null\b)'                                # 重定向 > 或 >>(目标不是 /dev/null; 放行 2>/dev/null)
    r'|\|\s*(?:bash|sh|python|perl|tee)\b'                  # 管道到解释器/tee
    r'|\|&'                                                 # 管道带 stderr
    r'|\s-(?:exec|execdir|ok|okdir|delete|fls|fprintf?)\b'  # find 写参数(任意位置; -fprint/-fprintf)
)


def _pipeline_segments(part: str) -> list:
    """按管道 | 拆分单段 part, 返回每段的 token 列表。
    跳过引号与 $(...) `...` 内的 |; || 已被外层 _split_merged_command 拆走, 不会进入此处。
    """
    protected, subs = _protect_substitutions(part)
    tokens = _tokenize_command(protected)
    segments, current = [], []
    for tok in tokens:
        s = tok.strip()
        if s == '|':
            if current:
                segments.append(current)
            current = []
        elif s:
            current.append(_restore_substitutions(tok, subs))
    if current:
        segments.append(current)
    return segments


def _check_readonly_form(seg: list) -> tuple:
    """反向校验: seg 是否符合首词允许的只读形态. 返回 (ok, reason). 默认拒绝.
    仅对 _READONLY_FORMS 中的命令生效; 其余命令返回 (True, None).
    三种形态: subs_opts(跳过选项找子命令) / subs(查 tokens[1]) / opts(白名单选项).
    """
    first = seg[0]
    form = _READONLY_FORMS.get(first)
    if not form:
        return True, None
    args = seg[1:]

    # ── subs_opts 型(systemctl/timedatectl/hostnamectl): 跳过前置选项 ──
    if form.get('subs_opts'):
        opts = form['opts']
        arg_opts = form.get('arg_opts', set())
        sub = ''
        i = 0
        while i < len(args):
            t = args[i]
            if t.startswith('--'):
                if t not in opts:
                    return False, f"{first} option not read-only: {t}"
                if t in arg_opts:
                    i += 2  # 跳过选项值
                else:
                    i += 1
            elif t.startswith('-') and len(t) > 1:
                if t in opts:
                    if t in arg_opts:
                        i += 2
                    else:
                        i += 1
                else:
                    # 尝试组合短选项拆解
                    chars = [f'-{c}' for c in t[1:]]
                    if any(c not in opts for c in chars):
                        return False, f"{first} option not read-only: {t}"
                    if any(c in arg_opts for c in chars):
                        i += 2
                    else:
                        i += 1
            else:
                sub = t
                break
        if sub:
            if sub not in form['subs']:
                return False, f"{first} subcommand not read-only: {sub}"
        # 无子命令 = 默认只读行为(如裸 systemctl = list-units)
        return True, None

    # ── subs 型(docker/redis-cli/crontab/openssl) ──
    if 'subs' in form:
        if first == 'docker':
            sub = args[0] if args else ''
            if sub in form['subs']:
                return True, None
            if sub in form.get('obj', {}) and len(args) > 1 and args[1] in form['obj'][sub]:
                return True, None
            return False, f"docker subcommand not read-only: {sub}"

        if first == 'redis-cli':
            for t in args:
                if t in form['no_flags']:
                    return False, f"redis-cli remote/forbidden flag: {t}"
            for i, t in enumerate(args):
                if not t.startswith('-'):
                    cmd = t.upper()
                    if cmd not in form['subs']:
                        return False, f"redis command not read-only: {t}"
                    if cmd == 'CONFIG':
                        nxt = args[i + 1].upper() if len(args) > i + 1 else ''
                        if nxt != 'GET':
                            return False, f"redis CONFIG only allows GET: {t}"
                    return True, None
            return False, "redis-cli missing command"

        if first == 'crontab':
            if args and args[0] in form['subs']:
                return True, None
            return False, "crontab only allows -l/--list"

        if first == 'openssl':
            sub = args[0] if args else ''
            if sub not in form['subs']:
                return False, f"openssl subcommand not read-only: {sub}"
            for t in args:
                if t in form['no_flags']:
                    return False, f"openssl write flag: {t}"
            return True, None

    # ── opts 型(curl/nginx/php/date/dmesg/hostname/ss) ──
    if 'opts' in form:
        has_opt = False
        for t in args:
            if t.startswith('--'):
                if t not in form['opts']:
                    return False, f"{first} option not read-only: {t}"
                has_opt = True
            elif t.startswith('-'):
                if t in form['opts']:
                    has_opt = True
                else:
                    chars = [f'-{c}' for c in t[1:]]
                    if not chars or any(c not in form['opts'] for c in chars):
                        return False, f"{first} option not read-only: {t}"
                    has_opt = True
            else:
                # 裸参(非 - 前缀)
                if form.get('no_args'):
                    return False, f"{first} does not accept arguments: {t}"
        if form.get('require_opt') and not has_opt:
            return False, f"{first} requires a read-only flag (e.g. nginx -t / php -l)"
        return True, None

    return True, None


def _check_substitutions(command: str) -> tuple:
    """提取并递归校验 $(...) 和反引号中的命令. 返回 (ok, reason).
    复用 _protect_substitutions 提取, 对每个替换项内部命令独立过 _is_readonly_command.
    安全: 内部命令同样过白名单/写操作符/形态检查, 安全模型与外部一致.
    """
    protected, subs = _protect_substitutions(command)
    for original in subs:
        if original.startswith('$('):
            inner = original[2:-1]  # 去掉 $( 和 )
        else:
            inner = original[1:-1]  # 去掉反引号
        inner = inner.strip()
        if inner:
            ok, reason = _is_readonly_command(inner)
            if not ok:
                return False, f"substitution blocked: {reason}"
    return True, None


def _is_readonly_command(command: str) -> tuple:
    """整条命令链是否纯只读, 返回 (ok, reason)。三层防线(均不动 RunCommand):
    ① 命令替换递归校验($()/反引号内命令过白名单) + shell 元字符拦截(进程替换 heredoc & 后台 换行);
    ② 危险命令黑名单 + 写操作符正则(重定向/管道解释器/tee/find 写参数);
    ③ 链式拆分(; && || → 管道 |)后逐段: 白名单首词 → 反向只读形态(_READONLY_FORMS).
    """
    # ①a 命令替换递归校验: $(basename x) → 提取 inner 过白名单; $(rm -rf /) → rm 不在白名单拒
    ok, reason = _check_substitutions(command)
    if not ok:
        return False, reason

    # ①b shell 元字符: 引号内同样拒(宁可杀错), 堵进程替换/heredoc/后台/换行 等注入
    m = _SHELL_METACHAR_RE.search(command)
    if m:
        return False, f"shell metacharacter blocked: {m.group(0)}"

    # ② 危险命令黑名单(rm -rf /, dd, mkfs, reboot, > /etc/passwd ...)
    dangerous, reason = _is_dangerous_command(command)
    if dangerous:
        return False, f"dangerous pattern: {reason}"

    for part in _split_merged_command(command):
        # 写操作符(重定向 / 管道到解释器 / tee / find 写参数)
        if _WRITE_OPERATOR_RE.search(part):
            return False, f"write operator in: {part}"
        # 每段管道(含右侧): 白名单 → 只读形态
        for seg in _pipeline_segments(part):
            if not seg:
                continue
            first = seg[0]
            if first not in _READONLY_COMMANDS:
                return False, f"command not in readonly whitelist: {first}"
            ok, reason = _check_readonly_form(seg)
            if not ok:
                return False, reason
            # 正向写子命令(全已移入 _READONLY_FORMS, 此 dict 为空; 保留以备未来扩展)
            subs = _WRITE_SUBCOMMANDS.get(first)
            if subs and len(seg) > 1 and seg[1] in subs:
                return False, f"write subcommand: {first} {seg[1]}"
    return True, None


@register_tool(category="Agent", name_cn="Read Only Command", risk_level="low", subagent_only=True)
class ReadOnlyCommand(RunCommand):
    """
    (sub-agent only) Execute a whitelisted read-only shell command to collect diagnostic evidence (logs, status, ports, configs, resource usage). Non-whitelisted or write-capable commands are rejected.

    When to use:
    - You are a sub-agent (Task worker) and panel tools cannot provide the needed diagnostic information.
    - Prefer this over any other command execution — it is risk_level=low and needs no confirmation.

    Usage tips:
    - Supports && ; || chains and pipes. Every segment's first token must be a common read-only utility (cat/grep/find/ls/ps/ss/top/vmstat/journalctl/dig/df/openssl/nginx -t/php -l, etc.).
    - Hard reject (even with a whitelisted head): process substitution (`<()`), `&` background, `\n` injection, redirects (> >> except >/dev/null), find -exec/-delete, non-read-only pipe targets (xargs/sed/awk/tee).
    - `$()` and backtick substitutions are validated recursively — the inner command must itself pass the whitelist (e.g. `$(hostname)` ok, `$(rm /tmp)` blocked).
    - Most commands are default-deny on subcommands/options — only their read-only forms pass (e.g. `systemctl status`, `docker ps`, `redis-cli info`, `curl -I`, `date -u`, `ss -tln`, `nginx -t`, `crontab -l`). SQL → MysqlQuery.

    Args:
        command: Read-only shell command (supports && ; || and pipes). Every segment must pass the whitelist.
        cwd: Working directory for the command.
        timeout: Timeout in milliseconds (default 30000 = 30s).
        description: Brief description of what this command does (for logging).
    """

    _tool_name = "ReadOnlyCommand"

    def execute(self, command: str, cwd: str = None,
                timeout: int = 30000, description: str = None) -> str:
        ok, reason = _is_readonly_command(command)
        if not ok:
            return _xml_response(self._tool_name, "error",
                                 f"Read-only check failed: {reason}")
        # 复用父类无状态执行: 强制 blocking, 不开放 session 以收紧状态面
        return super().execute(
            command=command, blocking=True, cwd=cwd,
            timeout=timeout, description=description,
        )
