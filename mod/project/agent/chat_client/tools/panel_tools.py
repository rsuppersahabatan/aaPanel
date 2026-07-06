# coding: utf-8
"""Panel operation toolset - 44 tools registered to ToolRegistry"""

import json
import os
import re
import sys
import subprocess
import time
from typing import List

from . import register_tool
from .base import _xml_response

_panel_path = '/www/server/panel'
os.chdir(_panel_path)
sys.path.insert(0, _panel_path)
sys.path.insert(0, _panel_path + "/class/")
sys.path.insert(0, _panel_path + "/class_v2/")

import public

try:
    from public.hook_import import hook_import

    hook_import()
except:
    pass

from public import lang


def _to_obj(params: dict):
    """Convert dict to panel obj object"""
    return public.to_dict_obj(params)


class _ServiceStatusEnricher:
    """Backfill s_status for services not covered by get_soft_status.

    Layered on top of the get_soft_status result, reusing panelPlugin detectors
    for the services it misses (php/memcached/tomcat/phpmyadmin + a generic
    fallback). Output stays structurally identical — same outer keys and the
    same inner 9 keys; on any error the wrapper is returned unchanged so the
    tool never breaks the base output.
    """

    _COVERED = frozenset({
        'nginx', 'mysql', 'apache', 'pure-ftpd', 'redis',
        'pgsql', 'openlitespeed', 'mongodb',
    })
    _PHP_RE = re.compile(r'^php(?:-fpm)?(?:-?(\d{1,2})(?:\.\d+)?)?$')
    _TITLES = {'tomcat': 'Tomcat', 'phpmyadmin': 'phpMyAdmin'}

    def __init__(self, plugin):
        self.plugin = plugin

    @classmethod
    def enrich(cls, wrapper, name):
        if not isinstance(wrapper, dict):
            return wrapper
        inner = wrapper.get('message')
        if not isinstance(inner, dict):
            return wrapper
        raw = (name or '').strip()
        family, phpver = cls._classify(raw)
        if not family or family in cls._COVERED:
            return wrapper
        try:
            from class_v2.panel_plugin_v2 import panelPlugin
            enricher = cls(panelPlugin())
        except Exception:
            return wrapper

        if family == 'php':
            # get_soft_status judges install via /www/server/<name>, which misses
            # php-fpm (real dir is /www/server/php/<ver>); re-judge via dir scan.
            running, version, installed = enricher._php(phpver)
            if installed:
                inner['status'] = True
                inner['setup'] = True
                inner['s_status'] = bool(running)
                if version:
                    inner['version'] = version
                if inner.get('title', '') in ('', raw):
                    inner['title'] = 'PHP' + (phpver or '')
            return wrapper

        # Non-php: leave uninstalled services untouched (s_status stays False).
        if not inner.get('status'):
            return wrapper
        try:
            running, version = enricher._detect(family, raw, phpver)
        except Exception:
            return wrapper
        if family in ('memcached', 'tomcat', 'phpmyadmin'):
            inner['s_status'] = bool(running)
            if version and not inner.get('version'):
                inner['version'] = version
            if inner.get('title', '') in ('', raw):
                inner['title'] = cls._TITLES.get(family, inner.get('title', ''))
        elif running:
            # Generic fallback: only flip to True when running is detected.
            inner['s_status'] = True
        return wrapper

    @classmethod
    def query(cls, names, fetch=None):
        """High-level entry: return a newline-joined status report, one line per
        service (e.g. 'nginx: installed, running, v1.24'). Encapsulates
        get_soft_status + enrich + describe."""
        if fetch is None:
            from class_v2.panelModelV2.publicModel import main as PublicMain
            fetch = PublicMain().get_soft_status
        lines = []
        for svc in names:
            data = cls.enrich(fetch(_to_obj({"name": svc})), svc)
            inner = data.get('message', {}) if isinstance(data, dict) else {}
            lines.append(cls._describe(svc, inner))
        return '\n'.join(lines)

    @classmethod
    def _describe(cls, svc, inner):
        """Render one service's status as a model-friendly line."""
        if not isinstance(inner, dict) or not inner.get('status'):
            return '{}: not installed'.format(svc)
        parts = ['installed', 'running' if inner.get('s_status') else 'stopped']
        version = inner.get('version', '')
        if version:
            parts.append('v' + version)
        return '{}: {}'.format(svc, ', '.join(parts))

    @classmethod
    def _classify(cls, raw):
        """Return (family, php_version). 'php' for any php/php-fpm/php-<ver>
        variant, else the raw name; php_version is dot-stripped (e.g. '74')."""
        n = (raw or '').strip().lower()
        if not n:
            return ('', None)
        m = cls._PHP_RE.match(n)
        if m:
            return ('php', m.group(1))
        return (n, None)

    def _detect(self, family, raw, phpver):
        """Return (running, version) for memcached/tomcat/phpmyadmin/generic."""
        if family == 'memcached':
            return (self._exists('memcached'), '')
        if family == 'tomcat':
            return (self._exists('jsvc') or self._exists('java'), '')
        if family == 'phpmyadmin':
            try:
                return (bool(self.plugin.get_phpmyadmin_stat()), '')
            except Exception:
                return (False, '')
        # Generic fallback: the raw name, its separator-stripped form, or a
        # common daemon alias.
        candidates = [raw, re.sub(r'[-_.]', '', raw),
                      {'apache': 'httpd', 'mysql': 'mysqld'}.get(raw, '')]
        return (any(self._exists(c) for c in candidates if c), '')

    def _exists(self, pname):
        try:
            return bool(self.plugin.process_exists(pname))
        except Exception:
            return False

    def _php(self, ver):
        """Detect php-fpm via installed /www/server/php/<digits> dirs.

        When ver is given only that version is checked; version joins detected
        versions like '7.4/8.0'."""
        base = '/www/server/php'
        installed = []
        if os.path.isdir(base):
            installed = [d for d in os.listdir(base)
                         if d.isdigit() and os.path.isdir(os.path.join(base, d))]
        if ver:
            installed = [v for v in installed if v == ver]
        if not installed:
            return (False, '', False)
        running, versions = False, []
        for v in installed:
            try:
                if self.plugin.get_php_status(v):
                    running = True
            except Exception:
                continue
            try:
                with open(os.path.join(base, v, 'version.pl'), 'r') as f:
                    content = f.read().strip()
                if content:
                    versions.append(content)
            except Exception:
                pass
        return (running, '/'.join(versions), True)


def _truncate_result(data, limit):
    """Best-effort truncate a tool result to `limit` items without losing info.
    Handles plain lists and common wrappers ({data/rows/list/records: [...]}).
    Returns data unchanged when no list is found (info-preserving fallback)."""
    def _slice(lst):
        total = len(lst)
        if total > limit:
            lst = lst[:limit]
            lst.append({"_truncated": True, "total": total, "limit": limit})
        return lst
    if isinstance(data, list):
        return _slice(data)
    if isinstance(data, dict):
        for key in ("data", "rows", "list", "records"):
            v = data.get(key)
            if isinstance(v, list):
                data[key] = _slice(v)
                return data
    return data


# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
# System Diagnostics
# ═══════════════════════════════════════════════════════════════
@register_tool(category="System", name_cn="Get System Resources", risk_level="low")
def GetSystemResources() -> str:
    """
    Get real-time system resource metrics: CPU load, memory, disk usage, OS version.

    Returns: Load Avg (1m/5m/15m), Memory (used/total + %), Disk / (used/total + %), OS version.

    Workflow: GetSystemResources -> GetTopProcesses (for process-level diagnosis).
    """
    try:
        # Load Average
        try:
            load1, load5, load15 = os.getloadavg()
            load_info = f"Load Avg: {load1:.2f}, {load5:.2f}, {load15:.2f}"
        except OSError:
            load_info = "Load Avg: N/A (Windows?)"

        # Memory
        mem_info = "Mem: Unknown"
        if os.path.exists('/proc/meminfo'):
            with open('/proc/meminfo', 'r') as f:
                lines = f.readlines()
                total = 0
                available = 0
                for line in lines:
                    if 'MemTotal' in line:
                        total = int(line.split()[1]) // 1024  # MB
                    if 'MemAvailable' in line:
                        available = int(line.split()[1]) // 1024  # MB
                used = total - available
                percent = (used / total * 100) if total > 0 else 0
                mem_info = f"Mem: {used}MB/{total}MB ({percent:.1f}%)"

        # Disk
        import shutil
        disk = shutil.disk_usage("/")
        total_gb = disk.total // (1024 ** 3)
        used_gb = disk.used // (1024 ** 3)
        disk_percent = (disk.used / disk.total * 100)
        disk_info = f"Disk (/): {used_gb}GB/{total_gb}GB ({disk_percent:.1f}%)"
        os_info = public.get_os_version()

        result = f"{load_info}\n{mem_info}\n{disk_info}\nOS: {os_info}"
        return _xml_response("GetSystemResources", "done", result)
    except Exception as e:
        return _xml_response("GetSystemResources", "error", f"Error getting resources: {str(e)}")


@register_tool(category="System", name_cn="Get Public IP", risk_level="low")
def GetPublicIP() -> str:
    """
    Get the server's public IP (via external probe) and local network IP.

    Returns both addresses for comparison:
    - Public IP: the address the internet sees, used for DNS A-record, SSL application, firewall rules.
    - Local IP: the server's primary network interface address (may differ from public IP behind NAT).

    If public IP detection fails, only local IP is returned.
    """
    result_parts = []

    # 公网 IP
    public_ip = None
    for api_url in ['https://api.ipify.org', 'https://ifconfig.me', 'https://ip.sb']:
        try:
            p = subprocess.run(
                ['curl', '-s', '--connect-timeout', '3', api_url],
                capture_output=True, text=True, timeout=5
            )
            candidate = p.stdout.strip()
            if candidate and re.match(r'^\d{1,3}(\.\d{1,3}){3}$', candidate):
                public_ip = candidate
                break
        except Exception:
            continue

    if public_ip:
        result_parts.append(f"Public IP: {public_ip}")
    else:
        result_parts.append("Public IP: N/A (detection failed)")

    # 本机网卡IP
    try:
        local_ip = public.GetLocalIp()
        result_parts.append(f"Local IP: {local_ip}")
    except Exception:
        result_parts.append("Local IP: N/A")

    return _xml_response("GetPublicIP", "done", "\n".join(result_parts))


@register_tool(category="System", name_cn="Get Top 10 Processes", risk_level="low")
def GetTopProcesses() -> str:
    """
    Get top 10 processes by CPU and top 10 by memory.

    Returns: Two sections - CPU TOP 10 and Memory TOP 10 (PID, user, %cpu, %mem, command).

    Workflow: GetSystemResources -> GetTopProcesses.
    """

    def _run_shell_cmd(command: list, timeout: int = 300) -> tuple:
        """
        Common function to execute shell commands.
        Returns (success: bool, output: str)
        """
        try:
            # Use shell=False for security when passing a list
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            output = result.stdout.strip()
            if not output:
                output = result.stderr.strip()

            return result.returncode == 0, output
        except subprocess.TimeoutExpired:
            return False, f"Error: Command timed out after {timeout} seconds."
        except FileNotFoundError:
            return False, f"Error: Command not found: {command[0]}"
        except Exception as e:
            return False, f"Error executing command: {str(e)}"

    output_parts = []

    # 1. CPU Top 10
    success_cpu, output_cpu = _run_shell_cmd(["ps", "-eo", "pid,user,%cpu,%mem,command", "--sort=-%cpu"])
    if success_cpu:
        lines = output_cpu.strip().splitlines()
        header = lines[0] if lines else ""
        top10 = lines[1:11]
        output_parts.append("--- CPU Usage TOP 10 ---")
        output_parts.append(header)
        output_parts.extend(top10)
    else:
        output_parts.append(f"{lang('Failed to get CPU TOP 10')}: {output_cpu}")

    output_parts.append("")  # 空行分隔

    # 2. Memory Top 10
    success_mem, output_mem = _run_shell_cmd(["ps", "-eo", "pid,user,%cpu,%mem,command", "--sort=-%mem"])
    if success_mem:
        lines = output_mem.strip().splitlines()
        header = lines[0] if lines else ""
        top10 = lines[1:11]
        output_parts.append("--- Memory Usage TOP 10 ---")
        output_parts.append(header)
        output_parts.extend(top10)
    else:
        output_parts.append(f"{lang('Failed to get Memory TOP 10')}: {output_mem}")

    return _xml_response("GetTopProcesses", "done", "\n".join(output_parts))


# Website Management
# ═══════════════════════════════════════════════════════════════

@register_tool(category="Website", name_cn="List Websites", risk_level="low")
def SiteList(search: str = "", limit: int = 100, include_health: bool = False,
             site_id_list: List[int] = None) -> str:
    """
    List all websites. Always call this first before any website operation.

    Returns: JSON array with id, name (domain), project_type, path, status, ps.
        Set include_health=True to also return ssl/php_version/backup_count/domain_count/domains per site.

    Workflow: SiteList -> SiteDelete / WebSiteBackup / AutoSSL / GetSitesConf / GetSitesLogs.
    ALL downstream website tools take `id` from this list as the primary key.

    Args:
        search: Optional domain filter keyword. e.g. "example.com".
        limit: Max items to return (default 100). Items beyond are omitted.
        include_health: Also return ssl/php_version/backup_count/domain_count/domains per site. Default False.
        site_id_list: Optional list of specific site IDs.
    """
    try:
        _fields = 'id,name,project_type,path,status,ps'
        if site_id_list:
            ids_in = [int(i) for i in site_id_list]
            ph = ','.join(['?'] * len(ids_in))
            sites = public.M('sites').field(_fields).where('id in ({})'.format(ph), tuple(ids_in)).select()
        elif search:
            sites = public.M('sites').field(_fields).where('name like ?', '%{}%'.format(search)).select()
        else:
            sites = public.M('sites').field(_fields).select()

        # 轻量索引模式: 直出
        if not include_health:
            sites = _truncate_result(sites, limit)
            return _xml_response("SiteList", "done", json.dumps(sites, ensure_ascii=False))

        # 诊断模式: 批量查 + 逐站富化 (ssl/php_version/backup_count/domain_count/domains)
        if not sites:
            return _xml_response("SiteList", "done", json.dumps([], ensure_ascii=False))

        from class_v2.data_v2 import data as _Data

        ids = [s['id'] for s in sites]

        bak_map = {}
        try:
            bak_rows = public.S('backup').where_in('pid', ids).where("type", "0").group('pid').field(
                'pid', 'count(*) as cnt', 'max(addtime) as last_backup_time').select()
            bak_map = {b['pid']: b for b in bak_rows}
        except Exception:
            pass

        domain_map = {}
        try:
            dom_rows = public.S('domain').where_in('pid', ids).field('pid', 'name').select()
            for _d in dom_rows:
                domain_map.setdefault(_d['pid'], []).append(_d['name'])
        except Exception:
            pass

        d = _Data()

        def _enrich(site):
            try:
                _ssl = d.get_site_ssl_info(site['name'])
                # 只保留诊断过期所需字段, 砍掉 issuer/notBefore/dns/subject
                site['ssl'] = {'endtime': _ssl['endtime'], 'notAfter': _ssl['notAfter']} \
                    if isinstance(_ssl, dict) else _ssl
            except Exception:
                site['ssl'] = -1
            try:
                site['php_version'] = d.get_php_version(site['name'])
            except Exception:
                site['php_version'] = 'Static'
            bak = bak_map.get(site['id'], {})
            site['backup_count'] = bak.get('cnt', 0)
            site['last_backup_time'] = bak.get('last_backup_time') or ''
            _doms = domain_map.get(site['id'], [])
            site['domains'] = _doms
            site['domain_count'] = len(_doms)
            return site

        sites = [_enrich(s) for s in sites]

        sites = _truncate_result(sites, limit)
        return _xml_response("SiteList", "done", json.dumps(sites, ensure_ascii=False, default=str))
    except Exception as e:
        return _xml_response("SiteList", "error", str(e))


@register_tool(category="Website", name_cn="Get PHP Versions", risk_level="low")
def SiteGetPHPVersions() -> str:
    """
    Get PHP versions installed on the server.

    Returns: JSON array of version codes. e.g. ["00","73","74","80","81","82","83","84"].
        "00" = pure static, "other" = custom.

    Workflow: SiteGetPHPVersions -> SiteCreate (pass version code).
    """
    try:
        import panel_site_v2
        data = panel_site_v2.panelSite().GetPHPVersion(public.to_dict_obj({}))
        return _xml_response("SiteGetPHPVersions", "done", json.dumps(data, ensure_ascii=False))
    except Exception as e:
        return _xml_response("SiteGetPHPVersions", "error", str(e))


@register_tool(category="Website", name_cn="Create Website", risk_level="medium")
def SiteCreate(domain: str, port: int = 80, version: str = "", ps: str = "", path: str = "",
               ftp: bool = False, ftp_username: str = "", ftp_password: str = "",
               sql: str = "", datauser: str = "", datapassword: str = "",
               codeing: str = "utf8", type_id: int = 0,
               force_ssl: int = 0,
               is_create_default_file: bool = True) -> str:
    """
    Create a new website with domain binding, optional FTP and database. Backend auto-applies SSL asynchronously (ssl_auto=1); not the AutoSSL tool.

    Args:
        domain: Primary domain. Required. e.g. "example.com" or "blog.example.com".
        port: Listen port. Default 80.
        version: PHP version code. Default "" (pure static). Call SiteGetPHPVersions first.
        ps: Remark. Optional.
        path: Website root directory. Optional, auto-generated.
        ftp: Create FTP account. Default False.
        ftp_username: FTP username. Optional when ftp=True, auto-generated if omitted.
        ftp_password: FTP password. Optional when ftp=True, auto-generated if omitted.
        sql: Database type. "MySQL" to create DB, "" to skip. Default "".
        datauser: Database username. Optional when sql="MySQL", auto-generated if omitted.
        datapassword: Database password. Optional when sql="MySQL", auto-generated if omitted.
        codeing: Database encoding. Default "utf8".
        type_id: Site type ID. Default 0.
        force_ssl: Force HTTPS redirect. Default 0.
        is_create_default_file: Create default index file. Default True.

    Workflow: SiteGetPHPVersions -> SiteCreate.
    """
    try:
        import panel_site_v2
        # 构造 webname JSON (后端要求 JSON 字符串)
        webname_obj = {
            "domain": domain,
            "domainlist": [],
            "count": 0,
        }
        params = {
            "webname": json.dumps(webname_obj, ensure_ascii=False),
            "port": str(port),
            "type": "PHP",
            "version": version or "00",
            "ps": ps or domain.replace(".", "_"),
            "path": path or f"/www/wwwroot/{domain}",
            "ftp": ftp,
            "sql": sql or "",
            "codeing": codeing,
            "type_id": type_id,
            "force_ssl": force_ssl,
            "ssl_auto": "1",
            "is_create_default_file": is_create_default_file,
        }
        if ftp:
            params["ftp_username"] = ftp_username or f"ftp_{domain.replace('.', '_')}"
            params["ftp_password"] = ftp_password or __import__('secrets').token_hex(8)
        if sql:
            params["datauser"] = datauser or f"sql_{domain.replace('.', '_')}"
            params["datapassword"] = datapassword or __import__('secrets').token_hex(8)
        data = panel_site_v2.panelSite().AddSite(_to_obj(params))
        return _xml_response("SiteCreate", "done", json.dumps(data, ensure_ascii=False))
    except Exception as e:
        return _xml_response("SiteCreate", "error", str(e))


@register_tool(category="Website", name_cn="Delete Website", risk_level="high")
def SiteDelete(id: int, webname: str = "") -> str:
    """
    Delete a website. Irreversible.

    Args:
        id: Website ID from SiteList. Required.
        webname: Website domain name. Optional.

    Workflow: SiteList -> SiteDelete.
    """
    try:
        import panel_site_v2
        params = {"id": id}
        if webname:
            params["webname"] = webname
        data = panel_site_v2.panelSite().DeleteSite(_to_obj(params))
        return _xml_response("SiteDelete", "done", json.dumps(data, ensure_ascii=False))
    except Exception as e:
        return _xml_response("SiteDelete", "error", str(e))


@register_tool(category="Website", name_cn="Set Website PHP Version", risk_level="high")
def SiteSetPHPVersion(site_id: int, version: str) -> str:
    """
    Switch a website's PHP version. May briefly interrupt the site while the web server reloads.

    Args:
        site_id: Site ID from SiteList. Required.
        version: PHP version code from SiteGetPHPVersions. Required. e.g. "74","83"; "00"=pure static, "other"=custom.

    Workflow: SiteGetPHPVersions -> SiteSetPHPVersion.

    Prefer this over manually editing the vhost PHP include.
    """
    try:
        site = public.M('sites').where('id=?', site_id).field('name').find()
        if not site:
            return _xml_response("SiteSetPHPVersion", "error", "Site {} not found".format(site_id))
        import panel_site_v2
        data = panel_site_v2.panelSite().SetPHPVersion(
            _to_obj({"siteName": site["name"], "version": version}))
        return _xml_response("SiteSetPHPVersion", "done", json.dumps(data, ensure_ascii=False))
    except Exception as e:
        return _xml_response("SiteSetPHPVersion", "error", str(e))


@register_tool(category="Website", name_cn="Get Website Config", risk_level="low")
def GetSitesConf(site_id_list: List[int] = None) -> str:
    """
    Get nginx/Apache vhost configuration for one or more websites.

    Use for: diagnosing 403/502/500 errors, checking rewrite rules, SSL, reverse proxy config.

    Args:
        site_id_list: List of site IDs from SiteList. Pass SPECIFIC sites; Empty = ALL sites
            (returns every vhost config and can be very large - prefer targeted queries).

    Workflow: SiteList -> GetSitesConf (takes id; resolves domain internally).
    """
    import json
    if not site_id_list:
        all_sites = public.M('sites').field('id,name,project_type').select()
        if not all_sites:
            return _xml_response("GetSitesConf", "done",
                                 json.dumps({"error": "No sites found in panel."}, ensure_ascii=False, indent=2))
        site_id_list = [s['id'] for s in all_sites]

    results = {}
    last_site_name = None
    for sid in site_id_list:
        site_data = public.M('sites').field('name,project_type').where("id=?", int(sid)).find()
        if not site_data:
            results[str(sid)] = {"error": "Site not found in panel."}
            continue

        site_name = site_data['name']
        last_site_name = site_name
        project_type = site_data['project_type'].lower()
        prefix = '' if project_type in ('php', 'proxy', 'phpmod', 'wp2') else project_type + '_'

        conf_path = f"/www/server/panel/vhost/nginx/{prefix}{site_name}.conf"
        if not os.path.exists(conf_path):
            conf_path = f"/www/server/panel/vhost/apache/{prefix}{site_name}.conf"
            if not os.path.exists(conf_path):
                results[site_name] = {"error": "Configuration file not found."}
                continue

        with open(conf_path, 'r') as f:
            results[site_name] = f.read()

    if len(site_id_list) == 1 and last_site_name in results:
        val = results[last_site_name]
        if not (isinstance(val, dict) and "error" in val):
            return _xml_response("GetSitesConf", "done", val)
    return _xml_response("GetSitesConf", "done", json.dumps(results, ensure_ascii=False, indent=2))


@register_tool(category="Website", name_cn="Get Website Access Logs", risk_level="low")
def GetSitesLogs(site_id_list: List[int] = None) -> str:
    """
    Get recent access logs for websites.

    Use for: analyzing traffic, HTTP status codes, diagnosing 404/500, detecting suspicious activity.

    Args:
        site_id_list: List of site IDs from SiteList. Pass SPECIFIC sites; Empty = ALL sites
            (aggregates every site's logs and can be very large - prefer targeted queries).

    Workflow: SiteList -> GetSitesLogs (takes id; resolves domain internally).
    """
    import json
    from logsModelV2.siteModel import main
    logs_model = main()

    if not site_id_list:
        all_sites = public.M('sites').field('id,name').select()
        if not all_sites:
            return _xml_response("GetSitesLogs", "done",
                                 json.dumps({"error": "No sites found in panel."}, ensure_ascii=False, indent=2))
        site_id_list = [s['id'] for s in all_sites]

    results = {}
    last_site_name = None
    for sid in site_id_list:
        site_data = public.M('sites').field('name').where("id=?", int(sid)).find()
        if not site_data:
            results[str(sid)] = {"error": "Site not found in panel."}
            continue
        site_name = site_data['name']
        last_site_name = site_name
        logs = logs_model.GetSiteLogs(public.to_dict_obj({"siteName": site_name})).get("message")
        results[site_name] = logs

    if len(site_id_list) == 1 and last_site_name in results:
        return _xml_response("GetSitesLogs", "done",
                             json.dumps(results[last_site_name], ensure_ascii=False, indent=2))
    return _xml_response("GetSitesLogs", "done", json.dumps(results, ensure_ascii=False, indent=2))


@register_tool(category="Website", name_cn="Get Website Traffic Data", risk_level="low")
def GetSiteOverview(site_id_list: List[int] = None, sort_by: str = "") -> str:
    """
    Get 7-day traffic statistics (UV, PV, bandwidth) for websites.

    Args:
        site_id_list: List of site IDs from SiteList. Pass SPECIFIC sites; Empty = ALL sites
            (can be large with many sites - prefer targeted queries, or use sort_by="traffic" for a ranked overview).
        sort_by: Sort field. Optional. "traffic" = sort by traffic desc. Empty = no sort.

    Returns: Per-site traffic data. When sort_by="traffic", returns ranked list for all sites.

    Workflow: SiteList -> GetSiteOverview (takes id; resolves domain internally).
    """
    import json
    from projectModelV2.monitorModel import main as monitor

    # 排序模式：直接返回聚合排名数据 (不依赖站点列表)
    if sort_by == "traffic":
        monitordata = monitor().get_overview(public.to_dict_obj({"metric": "traffic", "order": "desc"})).get("message")
        return _xml_response("GetSiteOverview", "done", json.dumps(monitordata, ensure_ascii=False, indent=2))

    if not site_id_list:
        all_sites = public.M('sites').field('id,name').select()
        if not all_sites:
            return _xml_response("GetSiteOverview", "done",
                                 json.dumps({"error": "No sites found in panel."}, ensure_ascii=False, indent=2))
        site_id_list = [s['id'] for s in all_sites]

    results = {}
    last_site_name = None
    for sid in site_id_list:
        site_data = public.M('sites').field('name').where("id=?", int(sid)).find()
        if not site_data:
            results[str(sid)] = {"error": "Site not found in panel."}
            continue
        site_name = site_data['name']
        last_site_name = site_name
        monitordata = monitor().get_overview(public.to_dict_obj({"site_name": site_name})).get("message")
        results[site_name] = monitordata

    if len(site_id_list) == 1 and last_site_name in results:
        return _xml_response("GetSiteOverview", "done",
                             json.dumps(results[last_site_name], ensure_ascii=False, indent=2))
    return _xml_response("GetSiteOverview", "done", json.dumps(results, ensure_ascii=False, indent=2))


# @register_tool(category="Website", name_cn="Backup Website", risk_level="high")
# def WebSiteBackup(site_ids: List[int]) -> str:
#     """
#     Backup websites by site ID. Auto-detects type: PHP (files only), WP/WP2 (files+DB), Node.js (files).
#
#     Prefer this over manual `RunCommand tar` — it detects site type and records backups in the panel for one-click restore.
#
#     Args:
#         site_ids: List of site IDs from SiteList. Required. e.g. [1, 2, 3].
#
#     Returns: Per-site backup trigger result. Backup runs asynchronously.
#
#     Workflow: SiteList -> WebSiteBackup.
#     """
#     import json
#
#     if not site_ids:
#         return _xml_response("WebSiteBackup", "error", "No site IDs provided. Use SiteList to list available sites.")
#
#     sids = [int(sid) for sid in site_ids]
#     site_results = []  # 每个站点的预检信息
#
#     # 1. 逐个查询站点信息，按类型分组
#     php_ids, wp_ids, node_ids = [], [], []
#     for sid in sids:
#         site_info = public.M('sites').where('id=?', (sid,)).field('id,name,project_type').find()
#         if not site_info:
#             site_results.append({"id": sid, "status": "error", "msg": "Site not found"})
#             continue
#
#         ptype = (site_info.get('project_type') or '').upper()
#         entry = {"id": sid, "name": site_info.get('name', ''), "type": ptype}
#
#         if ptype == 'PHP':
#             entry["backup_mode"] = "file-only"
#             php_ids.append(sid)
#         elif ptype in ('WP', 'WP2'):
#             entry["backup_mode"] = "full"
#             wp_ids.append(sid)
#         elif ptype == 'NODE':
#             entry["backup_mode"] = "file-only"
#             node_ids.append(sid)
#         else:
#             entry["status"] = "error"
#             entry["msg"] = "Unsupported type '{}'. Supported: PHP, WP/WP2, Node.".format(ptype)
#
#         site_results.append(entry)
#
#     # 2. 按类型各调一次备份接口
#     triggered = {"php": False, "wp": False, "node": False}
#
#     if php_ids:
#         try:
#             from panel_site_v2 import panelSite
#             args = public.to_dict_obj({'id': php_ids, 'bak_type': 0, 'site_type': 'php'})
#             res = panelSite().ai_php_wp_backup(args)
#             triggered["php"] = isinstance(res, dict) and res.get('status') == 0
#         except Exception:
#             pass
#
#     if wp_ids:
#         try:
#             from panel_site_v2 import panelSite
#             args = public.to_dict_obj({'id': wp_ids, 'bak_type': 3, 'site_type': 'wp'})
#             res = panelSite().ai_php_wp_backup(args)
#             triggered["wp"] = isinstance(res, dict) and res.get('status') == 0
#         except Exception:
#             pass
#
#     if node_ids:
#         try:
#             from mod.project.nodejs.comMod import main as nodejs_main
#             args = public.to_dict_obj({'id': node_ids, 'backup_type': 0})
#             res = nodejs_main().nodejs_backup(args)
#             triggered["node"] = isinstance(res, dict) and res.get('status') == 0
#         except Exception:
#             pass
#
#     # 3. 标记各站点触发结果
#     for entry in site_results:
#         if entry.get('status') == 'error':
#             continue  # 已标记错误的跳过
#         ptype = entry.get('type', '')
#         if ptype == 'PHP':
#             entry["status"] = "ok" if triggered["php"] else "error"
#             if not triggered["php"]:
#                 entry["msg"] = "PHP backup trigger failed"
#         elif ptype in ('WP', 'WP2'):
#             entry["status"] = "ok" if triggered["wp"] else "error"
#             if not triggered["wp"]:
#                 entry["msg"] = "WordPress backup trigger failed"
#         elif ptype == 'NODE':
#             entry["status"] = "ok" if triggered["node"] else "error"
#             if not triggered["node"]:
#                 entry["msg"] = "Node.js backup trigger failed"
#
#     success = sum(1 for r in site_results if r.get('status') == 'ok')
#     failed = sum(1 for r in site_results if r.get('status') == 'error')
#
#     output = {
#         "total": len(sids),
#         "success": success,
#         "failed": failed,
#         "results": site_results,
#         "progress_hint": "Backup is running asynchronously. Check progress in the backup log.",
#     }
#
#     status = "done" if failed == 0 else ("partial" if success > 0 else "error")
#     return _xml_response("WebSiteBackup", status, json.dumps(output, ensure_ascii=False, indent=2))


# ═══════════════════════════════════════════════════════════════
# Database Management
# ═══════════════════════════════════════════════════════════════

@register_tool(category="Database", name_cn="List Databases", risk_level="low")
def DBList(limit: int = 200) -> str:
    """
    List all databases with id, pid (parent site id, 0 = standalone), name, username, type,
    allowed IP (accept), sid (server id, 0 = local MySQL), conn_config (connection params:
    host/port/db_host etc), and backup_count.

    Returns: JSON array. Use id for DBDelete.

    Workflow: DBList -> DBCreate / DBDelete / DBChangePassword.

    Args:
        limit: Max rows to return (default 200). Rows beyond are omitted.
    """
    try:
        rows = public.M('databases').field('id,pid,name,username,accept,type,sid,conn_config').select()
        # 批量备份计数 (databases -> type='1', 一次 where_in)
        bak_map = {}
        try:
            ids = [r['id'] for r in rows]
            if ids:
                bak_rows = public.S('backup').where_in('pid', ids).where("type", "1").group('pid').field(
                    'pid', 'count(*) as cnt').select()
                bak_map = {b['pid']: b['cnt'] for b in bak_rows}
        except Exception:
            pass
        for r in rows:
            try:
                r['conn_config'] = json.loads(r['conn_config']) if r.get('conn_config') else {}
            except Exception:
                r['conn_config'] = {}
            r['backup_count'] = bak_map.get(r['id'], 0)
        rows = _truncate_result(rows, limit)
        return _xml_response("DBList", "done", json.dumps(rows, ensure_ascii=False, default=str))
    except Exception as e:
        return _xml_response("DBList", "error", str(e))


@register_tool(category="Database", name_cn="Create Database", risk_level="medium")
def DBCreate(name: str, password: str, db_user: str = "", ps: str = "") -> str:
    """
    Create a MySQL database (utf8mb4).

    Args:
        name: Database name. Required.
        password: Database password. Required.
        db_user: Database username. Optional, defaults to same as name.
        ps: Remark. Optional.

    Workflow: DBList -> DBCreate.

    Note: Remote access is enabled by default (address="%").
    """
    try:
        from class_v2.database_v2 import database
        params = {
            "name": name, "password": password,
            "db_user": db_user or name,
            "codeing": "utf8mb4", "sid": 0, "active": True,
            "address": "%", "ps": ps, "dtype": "MySQL",
        }
        data = database().AddDatabase(_to_obj(params))
        return _xml_response("DBCreate", "done", json.dumps(data, ensure_ascii=False))
    except Exception as e:
        return _xml_response("DBCreate", "error", str(e))


@register_tool(category="Database", name_cn="Delete Database", risk_level="high")
def DBDelete(id: int, name: str) -> str:
    """
    Delete a database. Irreversible.

    Args:
        id: Database ID from DBList. Required.
        name: Database name. Required.

    Workflow: DBList -> DBDelete.
    """
    try:
        from class_v2.database_v2 import database
        data = database().DeleteDatabase(_to_obj({"id": id, "name": name}))
        return _xml_response("DBDelete", "done", json.dumps(data, ensure_ascii=False))
    except Exception as e:
        return _xml_response("DBDelete", "error", str(e))


@register_tool(category="Database", name_cn="Change Database Password", risk_level="high")
def DBChangePassword(id: int, db_user: str, password: str) -> str:
    """
    Change the password of a panel-managed database user. Syncs BOTH MySQL and panel records.

    Args:
        id: Database id from DBList. Required.
        db_user: Database username (DBList 'username' field). Required.
        password: New password (no Chinese; limited special chars). Required.

    Workflow: DBList -> DBChangePassword.

    Note: This is the ONLY safe way to change a DB password - it keeps MySQL and panel
    records in sync. NEVER use MysqlExecute to alter user passwords.
    """
    try:
        from class_v2.database_v2 import database
        data = database().ResDatabasePassword(
            _to_obj({"id": id, "name": db_user, "password": password}))
        return _xml_response("DBChangePassword", "done", json.dumps(data, ensure_ascii=False))
    except Exception as e:
        return _xml_response("DBChangePassword", "error", str(e))


@register_tool(category="Database", name_cn="Backup Database", risk_level="high")
def DBBackup(db_id: int) -> str:
    """
    Back up a MySQL database (full dump to a timestamped .sql.zip). Blocks until the dump finishes; slow on large DBs.

    Args:
        db_id: Database ID from DBList (MySQL only). Required.

    Workflow: DBList -> DBBackup -> DBBackupList.

    Prefer this over raw mysqldump — it records the backup in the panel registry.
    """
    try:
        from class_v2.database_v2 import database
        data = database().ToBackup(_to_obj({"id": db_id}))
        return _xml_response("DBBackup", "done", json.dumps(data, ensure_ascii=False))
    except Exception as e:
        return _xml_response("DBBackup", "error", str(e))


@register_tool(category="Database", name_cn="List Database Backups", risk_level="low")
def DBBackupList(search: str = "", limit: int = 100) -> str:
    """
    (read-only) List MySQL database backup files across all databases, newest first.

    Args:
        search: Optional filename keyword to filter.
        limit: Max items (default 100).

    Workflow: DBBackup -> DBBackupList.
    """
    try:
        from class_v2.database_v2 import database
        params = {"p": 1, "limit": limit}
        if search:
            params["search"] = search
        data = database().GetBackup(_to_obj(params))
        return _xml_response("DBBackupList", "done", json.dumps(data, ensure_ascii=False))
    except Exception as e:
        return _xml_response("DBBackupList", "error", str(e))


# ═══════════════════════════════════════════════════════════════
# SSL Certificate Management
# ═══════════════════════════════════════════════════════════════

@register_tool(category="SSL", name_cn="List SSL Certificates", risk_level="low")
def SSLList(search: str = "", limit: int = 100) -> str:
    """
    List SSL certificates with domain, expiry, renewal status, and hash.

    Returns: JSON array. hash identifies each certificate.

    Args:
        search: Optional domain keyword to filter results.
        limit: Max items to return (default 100). Items beyond are omitted.
    """
    try:
        from class_v2.ssl_domainModelV2.api import DomainObject
        params = {"search": search} if search else {}
        data = DomainObject().list_ssl_info(_to_obj(params))
        data = _truncate_result(data, limit)
        return _xml_response("SSLList", "done", json.dumps(data, ensure_ascii=False))
    except Exception as e:
        return _xml_response("SSLList", "error", str(e))


@register_tool(category="Website", name_cn="Auto Apply SSL", risk_level="high")
def AutoSSL(site_id: int) -> str:
    """
    Auto-apply free SSL for a site (Let's Encrypt). Reuses existing valid certs if matched.

    Note: Let's Encrypt SSL can be applied using the server's public IP.

    Prefer this over `RunCommand certbot` — it reuses panel DNS accounts and records certs under panel management.

    Verification method is auto-decided: all domains have a DNS Provider -> DNS-01; otherwise HTTP-01 (wildcard domains require DNS-01). Blocks until the certificate is applied or fails, then reports the final result.

    Args:
        site_id: Site ID from SiteList. Required.

    Returns: Pre-check (site info, domain list, DNS resolution) plus the final apply result in ssl_result ({"status": bool, "msg": str}).

    Workflow: SiteList -> AutoSSL.
    """
    import json
    import socket

    sid = int(site_id)
    precheck = {}

    # 1. 查询站点信息
    try:
        precheck['site_info'] = public.M('sites').where('id=?', sid).field('id,name,project_type').find()
    except Exception as e:
        precheck['site_info'] = {'error': str(e)}

    # 2. 查询域名列表
    domain_names = []
    try:
        domain_records = public.M('domain').where('pid=?', sid).field('name').select()
        if domain_records and isinstance(domain_records, list):
            domain_names = [d.get('name', '') for d in domain_records if d.get('name')]
        precheck['domains'] = domain_names
    except Exception as e:
        precheck['domains'] = {'error': str(e)}

    # 3. A记录解析查询 (公共DNS + 本地DNS, 单域名超时3秒)
    dns_results = {}
    for domain in domain_names:
        record = {}
        # 公共DNS查询
        try:
            results = socket.getaddrinfo(domain, None, socket.AF_INET, socket.SOCK_STREAM)
            record['public_dns'] = sorted(set(r[4][0] for r in results))
        except Exception:
            record['public_dns'] = lang('unresolved')
        # 本地DNS查询
        try:
            p = subprocess.run(
                ['dig', '@127.0.0.1', domain, '+short', '+time=3'],
                capture_output=True, text=True, timeout=5
            )
            ips = sorted(set(
                line.strip() for line in p.stdout.strip().splitlines() if line.strip() and not line.startswith(';')))
            record['local_dns'] = ips if ips else lang('unresolved')
        except Exception:
            record['local_dns'] = lang('unresolved')
        dns_results[domain] = record
    precheck['dns_resolution'] = dns_results

    # 同步申请SSL, 阻塞至完成
    try:
        from ssl_domainModelV2.service import apply_site_ssl_sync
        precheck['ssl_result'] = apply_site_ssl_sync(sid)
    except Exception as e:
        precheck['ssl_result'] = {"status": False, "msg": f"SSL apply error: {e}"}

    return _xml_response("AutoSSL", "done", json.dumps(precheck, ensure_ascii=False, indent=2))


# ═══════════════════════════════════════════════════════════════
# DNS Provider & Records
# ═══════════════════════════════════════════════════════════════

@register_tool(category="DNS", name_cn="List DNS Providers", risk_level="low")
def DNSProviderList() -> str:
    """
    List DNS provider accounts with id, name, and alias.

    Returns: JSON array. id is used as pid/search_pid in all DNS record operations. Each entry also includes a 'domains' field.

    aaPanelDns is the panel's self-hosted DNS (powered by PowerDNS, zones in BIND9 format, no API credentials); other providers are third-party APIs.
    """
    try:
        from class_v2.ssl_domainModelV2.api import DomainObject
        data = DomainObject().list_dns_api(_to_obj({}))
        try:
            for d in data.get('message', {}).get('data', []):
                if 'api_key' in d:
                    d.pop('api_key')  # Remove sensitive API keys from output
        except:
            pass
        return _xml_response("DNSProviderList", "done", json.dumps(data, ensure_ascii=False))
    except Exception as e:
        return _xml_response("DNSProviderList", "error", str(e))


@register_tool(category="DNS", name_cn="List DNS Records", risk_level="low")
def DNSRecordList(search_pid: int, domain: str = "", search: str = "") -> str:
    """
    List DNS records under a provider.

    Args:
        search_pid: Provider ID from DNSProviderList.
        domain: Filter by domain. Optional.
        search: Filter by keyword. Optional.

    Workflow: DNSProviderList -> DNSRecordList -> DNSRecordDelete.
    """
    try:
        from class_v2.ssl_domainModelV2.api import DomainObject
        params = {"search_pid": search_pid}
        if domain:
            params["domain"] = domain
        if search:
            params["search"] = search
        data = DomainObject().list_dns_record(_to_obj(params))
        return _xml_response("DNSRecordList", "done", json.dumps(data, ensure_ascii=False))
    except Exception as e:
        return _xml_response("DNSRecordList", "error", str(e))


@register_tool(category="DNS", name_cn="Create DNS Record", risk_level="high")
def DNSRecordCreate(pid: int, domain: str, record: str, record_type: str,
                    record_value: str, ttl: int = 600, priority: int = 0,
                    proxy: int = 0, ps: str = "") -> str:
    """
    Create a DNS record under a configured DNS provider.

    Args:
        pid: Provider ID from DNSProviderList.
        domain: Domain name. e.g. "example.com".
        record: Record name. e.g. "www"/"@"(root)/"*"(wildcard).
        record_type: Record type. e.g. "A"/"AAAA"/"CNAME"/"MX"/"TXT"/"SRV".
        record_value: Record value. e.g. "1.2.3.4" for A record.
        ttl: TTL in seconds. Default 600.
        priority: MX/SRV priority. Default 0.
        proxy: Cloudflare CDN proxy only (ignored by other providers). 0=off, 1=on. Default 0.
        ps: Remark. Optional.

    Workflow: DNSProviderList -> DNSRecordList -> DNSRecordCreate.
    """
    try:
        from class_v2.ssl_domainModelV2.api import DomainObject
        params = {
            "pid": pid, "domain": domain, "record": record,
            "record_type": record_type, "record_value": record_value,
            "ttl": ttl, "priority": priority, "proxy": proxy,
        }
        if ps:
            params["ps"] = ps
        data = DomainObject().create_dns_record(_to_obj(params))
        return _xml_response("DNSRecordCreate", "done", json.dumps(data, ensure_ascii=False))
    except Exception as e:
        return _xml_response("DNSRecordCreate", "error", str(e))


@register_tool(category="DNS", name_cn="Delete DNS Record", risk_level="high")
def DNSRecordDelete(id: int) -> str:
    """
    Delete a DNS record by ID. Irreversible.

    Args:
        id: Record ID from DNSRecordList.

    Workflow: DNSRecordList -> DNSRecordDelete.
    """
    try:
        from class_v2.ssl_domainModelV2.api import DomainObject
        data = DomainObject().delete_dns_record(_to_obj({"id": id}))
        return _xml_response("DNSRecordDelete", "done", json.dumps(data, ensure_ascii=False))
    except Exception as e:
        return _xml_response("DNSRecordDelete", "error", str(e))


# @register_tool(category="DNS", name_cn="Edit DNS Record", risk_level="high")
# def DNSRecordEdit(id: int, pid: int, domain: str, record: str, record_type: str,
#                   record_value: str, ttl: int = 600, proxy: int = 0,
#                   priority: int = 0, ps: str = "") -> str:
#     """
#     Edit an existing DNS record.
#
#     Args:
#         id: Record ID from DNSRecordList. Required.
#         pid: Provider ID from DNSProviderList. Required.
#         domain: Domain name. Required.
#         record: Record name. Required.
#         record_type: Type. Required. e.g. "A"/"CNAME"/"MX"/"TXT".
#         record_value: New value. Required.
#         ttl: TTL in seconds. Default 600.
#         proxy: CloudFlare CDN proxy. 0=off, 1=on. Default 0.
#         priority: MX/SRV priority. Default 0.
#         ps: Remark. Optional.
#
#     Workflow: DNSRecordList -> DNSRecordEdit (get current values first).
#     """
#     try:
#         from class_v2.ssl_domainModelV2.api import DomainObject
#         params = {
#             "id": id, "pid": pid, "domain": domain, "record": record,
#             "record_type": record_type, "record_value": record_value,
#             "ttl": ttl, "proxy": proxy, "priority": priority, "ps": ps,
#         }
#         data = DomainObject().edit_dns_record(_to_obj(params))
#         return _xml_response("DNSRecordEdit", "done", json.dumps(data, ensure_ascii=False))
#     except Exception as e:
#         return _xml_response("DNSRecordEdit", "error", str(e))


# ═══════════════════════════════════════════════════════════════
# Plugin & Software Management
# ═══════════════════════════════════════════════════════════════

# @register_tool(category="Plugin", name_cn="List Software Store", risk_level="low")
# def PluginSoftList(type: str = "0", query: str = "", p: int = 1, limit: int = 15) -> str:
#     """
#     List software in the aaPanel app store. Supports type and keyword filtering.
#
#     Args:
#     #type: "0" = all (default), "-1" = installed only.
#         query: Search keyword. e.g. "nginx"/"docker"/"php". Optional.
#         p: Page number. Default 1.
#         limit: Items per page. Default 15.
#
#     Returns: Paginated list with versions info. Extract sName and m_version for PluginInstall.
#
#     Workflow: PluginSoftList -> PluginInstall.
#     """
#     try:
#         from class_v2.panel_plugin_v2 import panelPlugin
#         params = {"type": type, "p": p, "limit": limit}
#         if query:
#             params["query"] = query
#         data = panelPlugin().get_soft_list(_to_obj(params))
#         return _xml_response("PluginSoftList", "done", json.dumps(data, ensure_ascii=False))
#     except Exception as e:
#         return _xml_response("PluginSoftList", "error", str(e))
#
#
# @register_tool(category="Plugin", name_cn="Install Software", risk_level="high")
# def PluginInstall(sName: str, version: str) -> str:
#     """
#     Install a software package from the app store. This is an ASYNC trigger.
#
#     Args:
#         sName: Software name from PluginSoftList. Required.
#         version: m_version from PluginSoftList. Required. e.g. "1.24"/"8.2"/"5.7".
#
#     Workflow: PluginSoftList -> PluginInstall.
#
#     IMPORTANT: This is an asynchronous operation. The install runs in the background.
#     This tool ONLY triggers the install and returns immediately.
#     NEVER poll, wait, retry, or check install progress after calling this tool.
#     Just report the trigger result (success/failure) to the user and stop.
#     """
#     try:
#         from class_v2.panel_plugin_v2 import panelPlugin
#         params = {"sName": sName, "version": version}
#         data = panelPlugin().install_plugin(_to_obj(params))
#         return _xml_response("PluginInstall", "done", json.dumps(data, ensure_ascii=False))
#     except Exception as e:
#         return _xml_response("PluginInstall", "error", str(e))


# ═══════════════════════════════════════════════════════════════
# Service Management
# ═══════════════════════════════════════════════════════════════

def _service_op(service: str, action: str) -> str:
    """管理面板服务: 主路 system().ServiceAdmin (走 /etc/init.d/<service>);
    主路失败 (返回 status!=0 或抛异常) 才 fallback 到 systemctl, 用 is-active 验证成败.

    action: "restart" 或 "stop". 模块级唯一对外入口, 内部封装 fallback 细节.
    """
    tool = "ServiceRestart" if action == "restart" else "ServiceStop"

    def _msg(data) -> str:
        # 从 return_message 结构 ({status, message:{result}}) 提取可读错误信息
        if isinstance(data, dict):
            msg = data.get("message")
            if isinstance(msg, dict) and "result" in msg:
                return str(msg["result"])
            return json.dumps(data, ensure_ascii=False)
        return str(data)

    def _run_systemctl(svc: str, act: str):
        # 执行 systemctl <act> <svc>, 用 is-active 验证. 返回 (ok, detail)
        try:
            public.ExecShell("systemctl {} {}".format(act, svc))
        except Exception as e:
            return False, "exec error: " + str(e)
        res = public.ExecShell("systemctl is-active {}".format(svc))
        if isinstance(res, tuple):
            state = (res[0] or "").strip()
        elif isinstance(res, str):
            state = res.strip()
        else:
            state = ""
        if act == "restart":
            return state == "active", "is-active={}".format(state)
        return state in ("inactive", "failed", "deactivating"), "is-active={}".format(state)

    primary_msg = None
    # 主路: ServiceAdmin 优先, 保持当前工具行为
    try:
        from class_v2.system_v2 import system
        data = system().ServiceAdmin(_to_obj({"name": service, "type": action}))
        time.sleep(1)
        if isinstance(data, dict) and data.get("status") == 0:
            return _xml_response(tool, "done", json.dumps(data, ensure_ascii=False))
        primary_msg = _msg(data)
    except Exception as e:
        primary_msg = str(e)

    # 兜底: systemctl + is-active 验证
    ok, detail = _run_systemctl(service, action)
    time.sleep(1)
    if ok:
        return _xml_response(tool, "done", json.dumps(
            {"status": 0, "fallback": "systemctl", "primary_error": primary_msg, "detail": detail},
            ensure_ascii=False))
    return _xml_response(tool, "error",
                         "ServiceAdmin failed [{}]; systemctl fallback failed: {}".format(primary_msg, detail))


@register_tool(category="Service", name_cn="Get Service Status", risk_level="low")
def ServiceStatus(name_list: List[str]) -> str:
    """
    Query install/running status and version for one or more services.

    Args:
        name_list: Service names. Required. e.g. ["nginx", "php-74", "mysql"].

    Returns: One line per service, e.g. "nginx: installed, running, v1.24" or "mysql: not installed".

    Workflow: ServiceStatus -> ServiceRestart / ServiceStop.
    """
    try:
        names = name_list if isinstance(name_list, list) else [name_list]
        report = _ServiceStatusEnricher.query(names)
        return _xml_response("ServiceStatus", "done", report)
    except Exception as e:
        return _xml_response("ServiceStatus", "error", str(e))


@register_tool(category="Service", name_cn="Restart Service", risk_level="high")
def ServiceRestart(service: str) -> str:
    """
    Restart a panel-managed service. Use with caution on production servers.

    Routes to ServiceAdmin (/etc/init.d/<service>) first; on failure it falls back to `systemctl restart` and confirms via `systemctl is-active`.

    Prefer this over `RunCommand systemctl restart` for panel-managed services — it keeps panel state in sync.

    Args:
        service: Panel-managed service name. Required. e.g. "nginx"/"mysql"/"apache"/"php-fpm".

    Workflow: ServiceStatus -> ServiceRestart.
    """
    return _service_op(service, "restart")


@register_tool(category="Service", name_cn="Stop Service", risk_level="high")
def ServiceStop(service: str) -> str:
    """
    Stop a panel-managed service. Related functionality will become unavailable.

    Routes to ServiceAdmin (/etc/init.d/<service>) first; on failure it falls back to `systemctl stop` and confirms via `systemctl is-active`.

    Prefer this over `RunCommand systemctl stop` for panel-managed services — it keeps panel state in sync.

    Args:
        service: Panel-managed service name. Required. e.g. "nginx"/"mysql"/"apache"/"php-fpm".

    Workflow: ServiceStatus -> ServiceStop.
    """
    return _service_op(service, "stop")


# ═══════════════════════════════════════════════════════════════
# FTP Account Management
# ═══════════════════════════════════════════════════════════════

@register_tool(category="FTP", name_cn="List FTP Accounts", risk_level="low")
def FTPList() -> str:
    """
    List FTP accounts with id, name, path, status.

    Returns: JSON array. Use id for management.

    Workflow: FTPList -> FTPCreate.
    """
    try:
        rows = public.M('ftps').field('id,name,path,status,ps,addtime').select()
        return _xml_response("FTPList", "done", json.dumps(rows, ensure_ascii=False))
    except Exception as e:
        return _xml_response("FTPList", "error", str(e))


@register_tool(category="FTP", name_cn="Create FTP Account", risk_level="medium")
def FTPCreate(ftp_username: str, ftp_password: str, path: str, ps: str = "") -> str:
    """
    Create an FTP account.

    Args:
        ftp_username: Username. Required. Min 3 chars, no special characters.
        ftp_password: Password. Required. Min 6 chars.
        path: Root directory. Required. e.g. "/www/wwwroot/ftptest".
        ps: Remark. Optional.

    Workflow: FTPList -> FTPCreate.
    """
    try:
        from class_v2.ftp_v2 import ftp
        params = {"ftp_username": ftp_username, "ftp_password": ftp_password, "path": path, "ps": ps}
        data = ftp().AddUser(_to_obj(params))
        return _xml_response("FTPCreate", "done", json.dumps(data, ensure_ascii=False))
    except Exception as e:
        return _xml_response("FTPCreate", "error", str(e))


# ═══════════════════════════════════════════════════════════════
# Cron Job Management
# ═══════════════════════════════════════════════════════════════

@register_tool(category="Cron", name_cn="List Cron Jobs", risk_level="low")
def CronList(limit: int = 100) -> str:
    """
    List cron jobs with id, name, type, schedule, status, and command.

    Returns: JSON array. Use id for CronDelete.

    Workflow: CronList -> CronCreate / CronDelete.

    Args:
        limit: Max items to return (default 100). Items beyond are omitted.
    """
    try:
        from class_v2.crontab_v2 import crontab
        data = crontab().GetCrontab(_to_obj({}))
        data = _truncate_result(data, limit)
        return _xml_response("CronList", "done", json.dumps(data, ensure_ascii=False))
    except Exception as e:
        return _xml_response("CronList", "error", str(e))


@register_tool(category="Cron", name_cn="Create Cron Job", risk_level="medium")
def CronCreate(name: str, type: str, where1: str, sBody: str, sType: str = "toShell",
               hour: int = 0, minute: int = 0, user: str = "root",
               save: str = "", backupTo: str = "", sName: str = "",
               urladdress: str = "", db_type: str = "", notice: int = 0,
               notice_channel: str = "", save_local: int = 0) -> str:
    """
    Create a scheduled task.

    Args:
        name: Job name. Required. e.g. "Daily Backup".
        type: Schedule type. Required.
            "minute-n" -> where1: "*/5" (every N minutes)
            "hour" -> where1: "1" (at minute N of each hour)
            "hour-n" -> where1: "2" (every N hours)
            "day" -> where1: "" (daily, use hour+minute for time)
            "day-n" -> where1: "3" (every N days)
            "week" -> where1: "1" (day of week 0=Sun-6=Sat, use hour+minute for time)
            "month" -> where1: "15" (day of month, use hour+minute for time)
            "once" -> where1: "2025-12-31 01:30" (one-time)
        where1: Cycle/frequency value. Required. Format depends on type (see above).
        sBody: Shell command or script content. Required. Will be executed by cron when sType="toShell".
        sType: Task type. "toShell" (shell command), "toUrl" (request URL), "database"/"site"/"path" (backup), "logs"/"webshell"/"sync_time"/"startup_services" etc.
        hour: Execution hour for day/week/month types. Default 0.
        minute: Execution minute for day/week/month/hour types. Default 0.
        user: Execute user. Default "root".
        save: Backup retention count. Optional.
        backupTo: Backup storage location. Optional.
        sName: Backup scope for database/site type. Optional.
        urladdress: URL for toUrl type. Optional.
        db_type: Database type for database backup. Optional.
        notice: Enable notification. 0=off, 1=on. Default 0.
        notice_channel: Notification channel. Optional.
        save_local: Keep local copy. 0=off, 1=on. Default 0.

    Workflow: CronList -> CronCreate.
    """
    try:
        from class_v2.crontab_v2 import crontab
        params = {
            "name": name, "type": type, "where1": where1, "sBody": sBody, "sType": sType,
            "hour": hour, "minute": minute, "user": user,
            "save": save, "backupTo": backupTo, "sName": sName,
            "urladdress": urladdress, "db_type": db_type,
            "notice": notice, "notice_channel": notice_channel, "save_local": save_local,
        }
        data = crontab().AddCrontab(_to_obj(params))
        return _xml_response("CronCreate", "done", json.dumps(data, ensure_ascii=False))
    except Exception as e:
        return _xml_response("CronCreate", "error", str(e))


@register_tool(category="Cron", name_cn="Delete Cron Job", risk_level="high")
def CronDelete(id: int) -> str:
    """
    Delete a cron job. Irreversible.

    Args:
        id: Job ID from CronList. Required.

    Workflow: CronList -> CronDelete.
    """
    try:
        from class_v2.crontab_v2 import crontab
        data = crontab().DelCrontab(_to_obj({"id": id}))
        return _xml_response("CronDelete", "done", json.dumps(data, ensure_ascii=False))
    except Exception as e:
        return _xml_response("CronDelete", "error", str(e))


# ═══════════════════════════════════════════════════════════════
# SSH Security
# ═══════════════════════════════════════════════════════════════

@register_tool(category="SSH", name_cn="SSH Login Logs", risk_level="low")
def SSHLogList(limit: int = 100) -> str:
    """
    Get SSH login history: login time, IP, username, and result.

    Returns: JSON array of SSH login records.

    Workflow: SSHLogList -> SSHIntrusionList (if anomalies detected).

    Args:
        limit: Max records to return (default 100). Records beyond are omitted.
    """
    try:
        from mod.modController import Controller
        args = _to_obj({"mod_name": "ssh", "sub_mod_name": "com", "def_name": "get_ssh_list", "data": "{}"})
        data = Controller().model(args)
        data = _truncate_result(data, limit)
        return _xml_response("SSHLogList", "done", json.dumps(data, ensure_ascii=False))
    except Exception as e:
        return _xml_response("SSHLogList", "error", str(e))


@register_tool(category="SSH", name_cn="SSH Intrusion Detection", risk_level="low")
def SSHIntrusionList(limit: int = 100) -> str:
    """
    Get SSH intrusion detection records: brute-force attempts, anomalous logins.

    Returns: JSON array of intrusion events.

    Workflow: SSHLogList -> SSHIntrusionList -> FirewallPortRuleList / FirewallIPRuleList (block suspicious IPs).

    Args:
        limit: Max records to return (default 100). Records beyond are omitted.
    """
    try:
        from mod.modController import Controller
        args = _to_obj({"mod_name": "ssh", "sub_mod_name": "com", "def_name": "get_ssh_intrusion", "data": "{}"})
        data = Controller().model(args)
        data = _truncate_result(data, limit)
        return _xml_response("SSHIntrusionList", "done", json.dumps(data, ensure_ascii=False))
    except Exception as e:
        return _xml_response("SSHIntrusionList", "error", str(e))


# ═══════════════════════════════════════════════════════════════
# Firewall
# ═══════════════════════════════════════════════════════════════

@register_tool(category="Firewall", name_cn="List Port Rules", risk_level="low")
def FirewallPortRuleList(query: str = "", p: int = 1, limit: int = 20) -> str:
    """
    List port rules with pagination. Each rule has id, ports, protocol, address, types (accept/drop), brief.

    Args:
        query: Search keyword for port/brief/address. Optional.
        p: Page number. Default 1.
        limit: Items per page. Default 20.

    Returns: Paginated list of port rules.

    Workflow: FirewallPortRuleList -> FirewallPortRuleDelete.
    """
    try:
        from class_v2.safeModelV2.firewallModel import main as FirewallMain
        data = FirewallMain().get_rules_list(_to_obj({"query": query, "p": p, "limit": limit}))
        return _xml_response("FirewallPortRuleList", "done", json.dumps(data, ensure_ascii=False))
    except Exception as e:
        return _xml_response("FirewallPortRuleList", "error", str(e))


@register_tool(category="Firewall", name_cn="List IP Rules", risk_level="low")
def FirewallIPRuleList(limit: int = 200) -> str:
    """
    List IP rules. Each rule has id, address (IP/CIDR), types (accept/drop), brief.

    Returns: JSON array of IP rules.

    Workflow: FirewallIPRuleList -> FirewallIPRuleDelete.

    Args:
        limit: Max rules to return (default 200). Rules beyond are omitted.
    """
    try:
        from class_v2.safeModelV2.firewallModel import main as FirewallMain
        data = FirewallMain().get_ip_rules_list(_to_obj({}))
        data = _truncate_result(data, limit)
        return _xml_response("FirewallIPRuleList", "done", json.dumps(data, ensure_ascii=False))
    except Exception as e:
        return _xml_response("FirewallIPRuleList", "error", str(e))


@register_tool(category="Firewall", name_cn="List Port Forward Rules", risk_level="low")
def FirewallForwardList(query: str = "", p: int = 1, limit: int = 20) -> str:
    """
    (read-only) List port forwarding rules. Each rule has id, start_port, ended_ip, ended_port, protocol.

    Args:
        query: Search keyword for port. Optional.
        p: Page number. Default 1.
        limit: Items per page. Default 20.

    Returns: Paginated list of port forwarding rules.

    Read-only: no tool exists to create/delete forwarding rules. Manage them via the aaPanel Web GUI (Security -> Firewall).
    """
    try:
        from class_v2.safeModelV2.firewallModel import main as FirewallMain
        data = FirewallMain().get_forward_list(_to_obj({"query": query, "p": p, "limit": limit}))
        return _xml_response("FirewallForwardList", "done", json.dumps(data, ensure_ascii=False))
    except Exception as e:
        return _xml_response("FirewallForwardList", "error", str(e))


@register_tool(category="Firewall", name_cn="List Country Rules", risk_level="low")
def FirewallCountryList(query: str = "", p: int = 1, limit: int = 20) -> str:
    """
    (read-only) List country/region blocking rules. Each rule has id, country, brief.

    Args:
        query: Search keyword for country name. Optional.
        p: Page number. Default 1.
        limit: Items per page. Default 20.

    Returns: Paginated list of country rules.

    Read-only: no tool exists to create/delete country rules. Manage them via the aaPanel Web GUI (Security -> Firewall).
    """
    try:
        from class_v2.safeModelV2.firewallModel import main as FirewallMain
        data = FirewallMain().get_country_list(_to_obj({"query": query, "p": p, "limit": limit}))
        return _xml_response("FirewallCountryList", "done", json.dumps(data, ensure_ascii=False))
    except Exception as e:
        return _xml_response("FirewallCountryList", "error", str(e))


@register_tool(category="Firewall", name_cn="Create Port Rule", risk_level="high")
def FirewallPortRuleCreate(ports: str, protocol: str, types: str, address: str, brief: str = "") -> str:
    """
    Create a port firewall rule (accept or drop) for a single source IP.

    Prefer this over `RunCommand iptables/firewall-cmd` — it persists rules via the panel firewall manager (survives reboots and panel sync). Confirm independent SSH/console access before any firewall change (anti-lockout).

    Args:
        ports: Port number. Required. e.g. "80" or "80,443".
        protocol: "tcp" or "udp". Required.
        types: "accept" or "drop". Required.
        address: Source IPv4. Required. Must be a single IP (e.g. "192.168.1.100"). All-IPs ("0.0.0.0/0") and CIDR ranges are not supported.
        brief: Remark. Optional.

    Workflow: FirewallPortRuleList -> FirewallPortRuleCreate.
    """
    try:
        from class_v2.safeModelV2.firewallModel import main as FirewallMain
        params = {"ports": ports, "protocol": protocol, "types": types,
                  "address": address, "source": address, "brief": brief}
        data = FirewallMain().create_rules(_to_obj(params))
        return _xml_response("FirewallPortRuleCreate", "done", json.dumps(data, ensure_ascii=False))
    except Exception as e:
        return _xml_response("FirewallPortRuleCreate", "error", str(e))


@register_tool(category="Firewall", name_cn="Delete Port Rule", risk_level="high")
def FirewallPortRuleDelete(id: int, ports: str, address: str, types: str, protocol: str) -> str:
    """
    Delete a port firewall rule. Irreversible.

    Args:
        id: Rule ID from FirewallPortRuleList. Required.
        ports: Port number. Required.
        address: Source IP. Required.
        types: "accept" or "drop". Required.
        protocol: "tcp" or "udp". Required.

    Workflow: FirewallPortRuleList -> FirewallPortRuleDelete.
    """
    try:
        from class_v2.safeModelV2.firewallModel import main as FirewallMain
        params = {"id": id, "ports": ports, "address": address, "types": types, "protocol": protocol}
        data = FirewallMain().remove_rules(_to_obj(params))
        return _xml_response("FirewallPortRuleDelete", "done", json.dumps(data, ensure_ascii=False))
    except Exception as e:
        return _xml_response("FirewallPortRuleDelete", "error", str(e))


@register_tool(category="Firewall", name_cn="Create IP Rule", risk_level="high")
def FirewallIPRuleCreate(address: str, types: str, protocol: str = "tcp", brief: str = "") -> str:
    """
    Create an IP firewall rule (accept or drop) for a single IP across all ports.

    Prefer this over `RunCommand iptables/firewall-cmd` — it persists rules via the panel firewall manager. Confirm independent SSH/console access before any firewall change (anti-lockout).

    Args:
        address: Source IP. Required. Must be a single IP (e.g. "192.168.1.100"). CIDR ranges are not supported.
        types: "accept" or "drop". Required.
        protocol: "tcp" or "udp". Default "tcp".
        brief: Remark. Optional.

    Workflow: FirewallIPRuleList -> FirewallIPRuleCreate.
    """
    try:
        from class_v2.safeModelV2.firewallModel import main as FirewallMain
        params = {"address": address, "source": address, "types": types,
                  "protocol": protocol, "brief": brief}
        data = FirewallMain().create_ip_rules(_to_obj(params))
        return _xml_response("FirewallIPRuleCreate", "done", json.dumps(data, ensure_ascii=False))
    except Exception as e:
        return _xml_response("FirewallIPRuleCreate", "error", str(e))


@register_tool(category="Firewall", name_cn="Delete IP Rule", risk_level="high")
def FirewallIPRuleDelete(id: int, address: str, types: str) -> str:
    """
    Delete an IP firewall rule. Irreversible.

    Args:
        id: Rule ID from FirewallIPRuleList. Required.
        address: IP address. Required.
        types: "accept" or "drop". Required.

    Workflow: FirewallIPRuleList -> FirewallIPRuleDelete.
    """
    try:
        from class_v2.safeModelV2.firewallModel import main as FirewallMain
        params = {"id": id, "address": address, "types": types}
        data = FirewallMain().remove_ip_rules(_to_obj(params))
        return _xml_response("FirewallIPRuleDelete", "done", json.dumps(data, ensure_ascii=False))
    except Exception as e:
        return _xml_response("FirewallIPRuleDelete", "error", str(e))


# ═══════════════════════════════════════════════════════════════
# Notification (mod/base/push_mod)
# ═══════════════════════════════════════════════════════════════

@register_tool(category="Notification", name_cn="List Push Senders", risk_level="low")
def ListPushSenders() -> str:
    """
    List configured push channels (notification targets): id, sender_type, used, title.

    Returns: JSON array. Use sender_type in Notify `channels` to target specific channels.

    Workflow: ListPushSenders -> Notify.
    """
    try:
        from mod.base.push_mod.mods import SenderConfig
        senders = [{
            "id": s.get("id"),
            "sender_type": s.get("sender_type"),
            "used": s.get("used"),
            "title": (s.get("data") or {}).get("title", s.get("sender_type")),
        } for s in SenderConfig().config]
        senders = _truncate_result(senders, 100)
        return _xml_response("ListPushSenders", "done", json.dumps(senders, ensure_ascii=False))
    except Exception as e:
        return _xml_response("ListPushSenders", "error", str(e))


@register_tool(category="Notification", name_cn="Send Notification", risk_level="high")
def Notify(title: str, message: str, channels: List[str] = None) -> str:
    """
    Send a notification to configured push channels. HIGH RISK - sends to EXTERNAL services
    (mail/dingding/feishu/webhook/weixin/tg/discord); ensure the message has no secrets.

    Returns: JSON {sent, total, results:[{channel, ok, error}]}.

    Workflow: ListPushSenders -> Notify.

    Args:
        title: Notification title. Required.
        message: Notification body. Required.
        channels: Optional sender_type list, e.g. ["mail","discord"]. Empty = all enabled (sms skipped).

    Note: After delivering a summary, analysis, or large result, proactively offer to send it via
    this tool (e.g. "want this conclusion sent to your mail/feishu/discord?").
    """
    try:
        from script.notify_cli import send_notify  # shared with the standalone CLI (single source of truth)
        results = send_notify(title, message, channels)
        summary = {"sent": sum(1 for r in results if r["ok"]),
                   "total": len(results), "results": results}
        return _xml_response("Notify", "done", json.dumps(summary, ensure_ascii=False))
    except Exception as e:
        return _xml_response("Notify", "error", str(e))


# ═══════════════════════════════════════════════════════════════
# Security Baseline (read-only scan)
# ═══════════════════════════════════════════════════════════════

@register_tool(category="System", name_cn="Security Baseline Scan", risk_level="low")
def SecurityBaselineScan(components: List[str] = None) -> str:
    """
    (read-only) Scan the security baseline; returns FAILED checks per component. Changes nothing.

    Args:
        components: Subset to scan. Default ["ssh","panel","php","mysql"]. Available: ssh, panel, php, mysql, redis, memcache.

    Workflow: SecurityBaselineScan -> (report findings; repair manually via panel).
    """
    try:
        from class_v2.san_baseline_v2 import san_baseline
        sb = san_baseline()
        mapping = {
            "ssh": "ssh_security", "panel": "panel_security", "php": "php_security",
            "mysql": "mysql_security", "redis": "redis_security", "memcache": "memcache_security",
        }
        targets = components if components else ["ssh", "panel", "php", "mysql"]
        results = {}
        for c in targets:
            method = mapping.get(c)
            if not method:
                results[c] = [{"error": "unknown component '{}'".format(c)}]
                continue
            try:
                results[c] = getattr(sb, method)()
            except Exception as e:
                results[c] = [{"error": str(e)}]
        return _xml_response("SecurityBaselineScan", "done",
                             json.dumps(results, ensure_ascii=False, default=str))
    except Exception as e:
        return _xml_response("SecurityBaselineScan", "error", str(e))
