# coding: utf-8
import os
import re
import time
from typing import Any, Dict, List, Tuple

import public


SERVICE_NAME_RE = re.compile(r"^[A-Za-z0-9_.@:+-]+$")

DEFAULT_SERVICES = [
    {"target_key": "nginx", "target_name": "nginx"},
    {"target_key": "httpd", "target_name": "apache"},
    {"target_key": "mysqld", "target_name": "mysql"},
    {"target_key": "mariadbd", "target_name": "mariadb"},
    {"target_key": "redis", "target_name": "redis"},
    {"target_key": "pure-ftpd", "target_name": "pure-ftpd"},
    {"target_key": "memcached", "target_name": "memcached"},
    {"target_key": "mongodb", "target_name": "mongodb"},
    {"target_key": "pgsql", "target_name": "pgsql"},
]

LOCAL_SERVICE_DEFINITIONS = [
    {
        "family": "nginx",
        "target_key": "nginx",
        "target_name": "Nginx",
        "paths": ["/www/server/nginx/sbin/nginx", "/www/server/nginx/nginx/sbin/nginx", "/etc/init.d/nginx"],
    },
    {
        "family": "mysql",
        "target_key": "mysqld",
        "target_name": "MySQL",
        "paths": ["/www/server/mysql/bin/mysqld", "/etc/init.d/mysqld"],
    },
    {
        "family": "apache",
        "target_key": "httpd",
        "target_name": "Apache",
        "paths": ["/www/server/apache/bin/httpd", "/etc/init.d/httpd"],
    },
    {
        "family": "redis",
        "target_key": "redis",
        "target_name": "Redis",
        "paths": ["/www/server/redis/src/redis-server", "/etc/init.d/redis"],
    },
    {
        "family": "pure-ftpd",
        "target_key": "pure-ftpd",
        "target_name": "Pure-Ftpd",
        "paths": ["/www/server/pure-ftpd/sbin/pure-ftpd", "/etc/init.d/pure-ftpd"],
    },
    {
        "family": "memcached",
        "target_key": "memcached",
        "target_name": "Memcached",
        "paths": ["/usr/local/memcached/bin/memcached", "/etc/init.d/memcached"],
    },
    {
        "family": "mongodb",
        "target_key": "mongodb",
        "target_name": "MongoDB",
        "paths": ["/www/server/mongodb/bin/mongod", "/etc/init.d/mongodb"],
    },
    {
        "family": "pgsql",
        "target_key": "pgsql",
        "target_name": "PostgreSQL",
        "paths": ["/www/server/pgsql/bin/postgres", "/etc/init.d/pgsql"],
    },
]

PROCESS_CHECK_SERVICES = {
    "mysqld",
    "mariadbd",
    "redis",
    "pure-ftpd",
    "nginx",
    "httpd",
    "apache",
    "memcached",
    "mongodb",
    "pgsql",
}


def valid_service_name(name: str) -> bool:
    return bool(name and SERVICE_NAME_RE.match(name))


def normalize_service_targets(services: Any) -> List[Dict[str, Any]]:
    if not isinstance(services, list):
        return []
    result = []
    seen = set()
    for idx, item in enumerate(services):
        if isinstance(item, str):
            key = item.strip()
            name = key
            enabled = 1
            sort = idx
            extra = {}
        elif isinstance(item, dict):
            key = str(item.get("target_key") or item.get("name") or "").strip()
            name = str(item.get("target_name") or item.get("name") or key).strip()
            enabled = int(item.get("enabled", 1))
            sort = int(item.get("sort", idx))
            extra = item.get("extra", {})
        else:
            continue
        if not valid_service_name(key) or key in seen:
            continue
        seen.add(key)
        service_family = str(item.get("service_family") or item.get("family") or "").strip() if isinstance(item, dict) else ""
        if not service_family and key.startswith("php-fpm-"):
            service_family = "php"
        result.append({
            "target_key": key,
            "target_name": name or key,
            "enabled": 1 if enabled else 0,
            "sort": sort,
            "extra": extra if isinstance(extra, dict) else {},
            "service_family": service_family,
            "version": str(item.get("version") or "").strip() if isinstance(item, dict) else "",
        })
    return result


def keep_single_version_services(services: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result = []
    seen_version_family = set()
    for item in normalize_service_targets(services):
        family = item.get("service_family") or ("php" if item["target_key"].startswith("php-fpm-") else "")
        if family == "php":
            if family in seen_version_family:
                continue
            seen_version_family.add(family)
        result.append(item)
    return result


def service_unknown_statuses(services: List[Dict[str, Any]], error_msg: str) -> List[Dict[str, Any]]:
    now = int(time.time())
    result = []
    for item in normalize_service_targets(services):
        result.append({
            "name": item["target_key"],
            "target_key": item["target_key"],
            "target_name": item["target_name"],
            "status": 2,
            "running": False,
            "state": "unknown",
            "error_msg": error_msg,
            "ts": now,
        })
    return result


def collect_local_service_status(services: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    now = int(time.time())
    result = []
    for item in normalize_service_targets(services):
        if not int(item.get("enabled", 1)):
            continue
        running, err = _check_local_service(item["target_key"])
        status = 1 if running else 0
        if err and not running:
            status = 2
        result.append({
            "name": item["target_key"],
            "target_key": item["target_key"],
            "target_name": item["target_name"],
            "status": status,
            "running": bool(running),
            "state": "active" if running else ("unknown" if err else "inactive"),
            "error_msg": err,
            "ts": now,
        })
    return result


def discover_local_services() -> Dict[str, Any]:
    services = []
    for item in LOCAL_SERVICE_DEFINITIONS:
        if not any(os.path.exists(path) for path in item["paths"]):
            continue
        status = collect_local_service_status([{
            "target_key": item["target_key"],
            "target_name": item["target_name"],
            "service_family": item["family"],
        }])
        status_item = status[0] if status else {}
        services.append(_service_option(
            target_key=item["target_key"],
            target_name=item["target_name"],
            family=item["family"],
            running=bool(status_item.get("running", False)),
            status=int(status_item.get("status", 0)),
            state=str(status_item.get("state") or "inactive"),
        ))

    for version in _installed_php_versions():
        key = "php-fpm-{}".format(version)
        status = collect_local_service_status([{
            "target_key": key,
            "target_name": "PHP {}".format(_format_php_version(version)),
            "service_family": "php",
            "version": version,
        }])
        status_item = status[0] if status else {}
        services.append(_service_option(
            target_key=key,
            target_name="PHP {}".format(_format_php_version(version)),
            family="php",
            version=version,
            version_name=_format_php_version(version),
            running=bool(status_item.get("running", False)),
            status=int(status_item.get("status", 0)),
            state=str(status_item.get("state") or "inactive"),
            is_versioned=1,
        ))

    return {
        "services": services,
        "groups": build_service_groups(services),
    }


def get_service_file_probe_paths() -> List[str]:
    paths = []
    for item in LOCAL_SERVICE_DEFINITIONS:
        paths.extend(item["paths"])
    for version in _candidate_php_versions():
        paths.extend(_php_version_paths(version))
    return _dedupe(paths)


def build_service_options_from_file_exists(existing_paths: Any) -> Dict[str, Any]:
    if isinstance(existing_paths, (list, tuple, set)):
        exists_map = {str(path): True for path in existing_paths}
    elif isinstance(existing_paths, dict):
        exists_map = {str(path): bool(value) for path, value in existing_paths.items()}
    else:
        exists_map = {}

    services = []
    for item in LOCAL_SERVICE_DEFINITIONS:
        if not any(exists_map.get(path) for path in item["paths"]):
            continue
        services.append(_service_option(
            target_key=item["target_key"],
            target_name=item["target_name"],
            family=item["family"],
            status=2,
            state="unknown",
        ))

    for version in _candidate_php_versions():
        if not any(exists_map.get(path) for path in _php_version_paths(version)):
            continue
        services.append(_service_option(
            target_key="php-fpm-{}".format(version),
            target_name="PHP {}".format(_format_php_version(version)),
            family="php",
            version=version,
            version_name=_format_php_version(version),
            status=2,
            state="unknown",
            is_versioned=1,
        ))

    return {
        "services": services,
        "groups": build_service_groups(services),
    }


def build_service_groups(services: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    groups = []
    group_map = {}
    for item in services:
        family = item.get("service_family") or item.get("family") or item.get("target_key")
        if not family:
            continue
        if family not in group_map:
            group_map[family] = {
                "family": family,
                "target_name": "PHP" if family == "php" else item.get("target_name", family),
                "type": "version" if family == "php" else "single",
                "select_mode": "single" if family == "php" else "toggle",
                "multiple": 0 if family == "php" else 1,
                "services": [],
            }
            groups.append(group_map[family])
        group_map[family]["services"].append(item)

    for group in groups:
        if group["family"] == "php":
            group["services"].sort(key=lambda x: x.get("version", ""))
        else:
            group["services"].sort(key=lambda x: x.get("sort", 0))
    return groups


def _installed_php_versions() -> List[str]:
    versions = []
    for version in _candidate_php_versions():
        for path in _php_version_paths(version):
            if os.path.exists(path):
                versions.append(str(version))
                break
    return versions


def _candidate_php_versions() -> List[str]:
    try:
        versions = public.get_php_versions()
    except Exception:
        versions = ['52', '53', '54', '55', '56', '70', '71', '72', '73', '74', '80', '81', '82', '83', '84', '85']
    return [str(version) for version in versions if re.match(r"^\d{2}$", str(version))]


def _php_version_paths(version: str) -> List[str]:
    return [
        "/www/server/php/{}/sbin/php-fpm".format(version),
        "/www/server/php/{}/bin/php".format(version),
        "/etc/init.d/php-fpm-{}".format(version),
    ]


def _dedupe(items: List[str]) -> List[str]:
    result = []
    seen = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _format_php_version(version: str) -> str:
    version = str(version)
    if len(version) == 2 and version.isdigit():
        return "{}.{}".format(version[0], version[1])
    return version


def _service_option(
        target_key: str,
        target_name: str,
        family: str,
        version: str = "",
        version_name: str = "",
        running: bool = False,
        status: int = 0,
        state: str = "inactive",
        is_versioned: int = 0,
) -> Dict[str, Any]:
    return {
        "target_type": "service",
        "target_key": target_key,
        "target_name": target_name,
        "service_family": family,
        "version": version,
        "version_name": version_name,
        "enabled": 0,
        "installed": 1,
        "is_versioned": int(is_versioned),
        "status": int(status),
        "running": bool(running),
        "state": state,
        "sort": 0,
    }


def _check_local_service(name: str) -> Tuple[bool, str]:
    if not valid_service_name(name):
        return False, "Invalid service name"
    if name in PROCESS_CHECK_SERVICES or name.find("php-fpm") != -1:
        try:
            from system import system
            return bool(system().check_service_status(name)), ""
        except Exception as e:
            return False, str(e)

    cmd = (
        "if command -v systemctl >/dev/null 2>&1; then "
        "systemctl is-active --quiet {name}; "
        "else service {name} status >/dev/null 2>&1; fi; echo $?"
    ).format(name=name)
    try:
        stdout, stderr = public.ExecShell(cmd)
        lines = str(stdout or "").strip().splitlines()
        return bool(lines and lines[-1].strip() == "0"), str(stderr or "")
    except Exception as e:
        return False, str(e)
