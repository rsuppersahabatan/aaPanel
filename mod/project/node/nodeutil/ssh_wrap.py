import json
import os.path
import time
import traceback
from typing import Optional, Tuple, Callable, Union, Dict, List
from mod.base.ssh_executor import SSHExecutor, CommandResult
from mod.project.node.dbutil import ServerNodeDB, Node
from mod.project.node.nodeutil.monitor_service import build_service_groups, normalize_service_targets, service_unknown_statuses

import public

def is_much_difference(a:float, b:float)->bool:
    if a == 0 or b == 0:
        return True
    ratio = a / b
    return ratio >= 10 or ratio <= 0.1


def _shell_single_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


class SSHApi:
    is_local = False
    _local_scripts_dir = os.path.join(os.path.dirname(__file__), "ssh_warp_scripts")

    def __init__(self, host, port: int=22, username: str="root", password=None, pkey=None,
                 pkey_passwd=None, threading_mod=False, timeout=20):
        self._real_ssh_conf = {
            "host": host,
            "username": username,
            "port": port,
            "password": password,
            "key_file": "",
            "passphrase": pkey_passwd,
            "key_data": pkey,
            "strict_host_key_checking": False,
            "allow_agent": False,
            "look_for_keys": False,
            "threading_mod": threading_mod,
            "timeout": timeout,
        }
        self._ssh_executor: Optional[SSHExecutor] = None


    @classmethod
    def new_by_id(cls, node_id: int, threading_mod=False) -> Optional["SSHApi"]:
        data = ServerNodeDB().get_node_by_id(node_id)
        if not data or not isinstance(data, dict):
            return None
        data["ssh_conf"] = json.loads(data["ssh_conf"])
        if not data["ssh_conf"]:
            return None
        data["ssh_conf"]["threading_mod"] = threading_mod
        return cls(**data["ssh_conf"])

    def _get_ssh_executor(self) -> SSHExecutor:
        if self._ssh_executor:
            return self._ssh_executor
        self._ssh_executor = SSHExecutor(**self._real_ssh_conf)
        return self._ssh_executor

    def get_net_work(self) -> Tuple[Optional[dict], str]:
        data, err = self._run_script("system_info.sh")
        if err:
            return None, err
        if not data.exit_code == 0:
            return None, data.stderr
        try:
            data = json.loads(data.stdout)
            if isinstance(data, dict) and "cpu" in data and "mem" in data:
                return self._tans_net_work_form_data(data), ""
            return None, "data in wrong format: %s" % str(data)
        except Exception as e:
            return None, str(e)

    def get_service_status(self, services) -> Tuple[List[dict], str]:
        service_list = [item for item in normalize_service_targets(services) if int(item.get("enabled", 1)) == 1]
        if not service_list:
            return [], ""
        service_args = " ".join(_shell_single_quote(item["target_key"]) for item in service_list)
        cmd = """
for svc in {service_args}; do
  if command -v systemctl >/dev/null 2>&1; then
    systemctl is-active --quiet "$svc"
    rc=$?
    state=$(systemctl is-active "$svc" 2>/dev/null || true)
  else
    service "$svc" status >/dev/null 2>&1
    rc=$?
    if [ "$rc" = "0" ]; then state="active"; else state="inactive"; fi
  fi
  if [ "$rc" = "0" ]; then running=1; else running=0; fi
  printf '%s\\t%s\\t%s\\n' "$svc" "$running" "$state"
done
""".format(service_args=service_args)
        executor = None
        try:
            executor = self._get_ssh_executor()
            executor.open()
            exit_code, stdout, stderr = executor.run(cmd)
            if exit_code != 0 and not stdout:
                return service_unknown_statuses(service_list, stderr or "Service status check failed"), stderr
            target_map = {item["target_key"]: item for item in service_list}
            now = int(time.time())
            result = []
            for line in str(stdout or "").splitlines():
                parts = line.split("\t")
                if len(parts) < 3:
                    continue
                key = parts[0].strip()
                item = target_map.get(key)
                if not item:
                    continue
                running = parts[1].strip() == "1"
                result.append({
                    "name": key,
                    "target_key": key,
                    "target_name": item["target_name"],
                    "status": 1 if running else 0,
                    "running": running,
                    "state": parts[2].strip() or ("active" if running else "inactive"),
                    "error_msg": "",
                    "ts": now,
                })
            if not result:
                return service_unknown_statuses(service_list, stderr or "Service status data is empty"), stderr
            return result, ""
        except RuntimeError:
            return service_unknown_statuses(service_list, "SSH connection failed"), "SSH connection failed"
        except Exception as e:
            return service_unknown_statuses(service_list, str(e)), str(e)
        finally:
            if executor:
                executor.close()

    def get_service_options(self) -> Tuple[Dict[str, list], str]:
        cmd = r"""
check_status() {
  svc="$1"
  if command -v systemctl >/dev/null 2>&1; then
    systemctl is-active --quiet "$svc"
    rc=$?
    state=$(systemctl is-active "$svc" 2>/dev/null || true)
  else
    service "$svc" status >/dev/null 2>&1
    rc=$?
    if [ "$rc" = "0" ]; then state="active"; else state="inactive"; fi
  fi
  if [ "$rc" = "0" ]; then running=1; else running=0; fi
  printf '%s\t%s' "$running" "$state"
}
emit_service() {
  family="$1"; key="$2"; label="$3"; paths="$4"
  exists=0
  old_ifs="$IFS"; IFS=":"
  for p in $paths; do
    if [ -e "$p" ]; then exists=1; break; fi
  done
  IFS="$old_ifs"
  if [ "$exists" = "1" ]; then
    status=$(check_status "$key")
    printf 'SERVICE\t%s\t%s\t%s\t\t\t%s\n' "$family" "$key" "$label" "$status"
  fi
}
emit_service nginx nginx Nginx "/www/server/nginx/sbin/nginx:/www/server/nginx/nginx/sbin/nginx:/etc/init.d/nginx"
emit_service mysql mysqld MySQL "/www/server/mysql/bin/mysqld:/etc/init.d/mysqld"
emit_service apache httpd Apache "/www/server/apache/bin/httpd:/etc/init.d/httpd"
emit_service redis redis Redis "/www/server/redis/src/redis-server:/etc/init.d/redis"
emit_service pure-ftpd pure-ftpd Pure-Ftpd "/www/server/pure-ftpd/sbin/pure-ftpd:/etc/init.d/pure-ftpd"
emit_service memcached memcached Memcached "/usr/local/memcached/bin/memcached:/etc/init.d/memcached"
emit_service mongodb mongodb MongoDB "/www/server/mongodb/bin/mongod:/etc/init.d/mongodb"
emit_service pgsql pgsql PostgreSQL "/www/server/pgsql/bin/postgres:/etc/init.d/pgsql"
if [ -d /www/server/php ]; then
  for dir in /www/server/php/[0-9][0-9]; do
    [ -d "$dir" ] || continue
    ver=$(basename "$dir")
    if [ -x "$dir/sbin/php-fpm" ] || [ -x "$dir/bin/php" ] || [ -e "/etc/init.d/php-fpm-$ver" ]; then
      status=$(check_status "php-fpm-$ver")
      major=$(printf '%s' "$ver" | cut -c1)
      minor=$(printf '%s' "$ver" | cut -c2)
      printf 'SERVICE\tphp\tphp-fpm-%s\tPHP %s.%s\t%s\t%s.%s\t%s\n' "$ver" "$major" "$minor" "$ver" "$major" "$minor" "$status"
    fi
  done
fi
"""
        executor = None
        try:
            executor = self._get_ssh_executor()
            executor.open()
            exit_code, stdout, stderr = executor.run(cmd)
            if exit_code != 0 and not stdout:
                return {"services": [], "groups": []}, stderr or "Service discovery failed"
            services = []
            for line in str(stdout or "").splitlines():
                parts = line.split("\t")
                if len(parts) < 8 or parts[0] != "SERVICE":
                    continue
                running = parts[6].strip() == "1"
                services.append({
                    "target_type": "service",
                    "service_family": parts[1].strip(),
                    "target_key": parts[2].strip(),
                    "target_name": parts[3].strip(),
                    "version": parts[4].strip(),
                    "version_name": parts[5].strip(),
                    "enabled": 0,
                    "installed": 1,
                    "is_versioned": 1 if parts[1].strip() == "php" else 0,
                    "status": 1 if running else 0,
                    "running": running,
                    "state": parts[7].strip() or ("active" if running else "inactive"),
                    "sort": 0,
                })
            return {"services": services, "groups": build_service_groups(services)}, ""
        except RuntimeError:
            return {"services": [], "groups": []}, "SSH connection failed"
        except Exception as e:
            return {"services": [], "groups": []}, str(e)
        finally:
            if executor:
                executor.close()

    @staticmethod
    def _tans_net_work_form_data(data: dict):
        data["mem"]["memAvailable"] = round(data["mem"]["memAvailable"] / 1024 / 1024, 2)
        data["mem"]["memBuffers"] = round(data["mem"]["memBuffers"] / 1024 / 1024, 2)
        data["mem"]["memCached"] = round(data["mem"]["memCached"] / 1024 / 1024, 2)
        data["mem"]["memFree"] = round(data["mem"]["memFree"] / 1024 / 1024, 2)
        data["mem"]["memRealUsed"] = round(data["mem"]["memRealUsed"] / 1024 / 1024, 2)
        data["mem"]["memShared"] = round(data["mem"]["memShared"] / 1024 / 1024, 2)
        data["mem"]["memTotal"] = round(data["mem"]["memTotal"] / 1024 / 1024, 2)
        data["physical_memory"]= round(data["physical_memory"] / 1024 / 1024, 2)
        if is_much_difference(data["mem"]["memTotal"], data["physical_memory"]):
            if data["mem"]["memTotal"] >= 1024:
                data["mem"]["memNewTotal"] = "%.2fGB" % (data["mem"]["memTotal"] / 1024)
            else:
                data["mem"]["memNewTotal"] = "%.2fMB" % data["mem"]["memTotal"]
        else:
            if data["physical_memory"] >= 1024:
                data["mem"]["memNewTotal"] = "%.2fGB" % (data["physical_memory"] / 1024)
            else:
                data["mem"]["memNewTotal"] = "%.2fMB" % data["physical_memory"]
        return data

    def _run_script(self, script_name: str) -> Tuple[Optional[CommandResult], str]:
        local_file = os.path.join(self._local_scripts_dir, script_name)
        if not os.path.exists(local_file):
            return None, "Script does not exist"
        executor = None
        try:
            executor = self._get_ssh_executor()
            executor.open()
            result = executor.execute_local_script_collect(local_file)
            return result, ""
        except RuntimeError:
            return None, "SSH connection failed"
        except Exception as e:
            return None, str(e)
        finally:
            if executor:
                executor.close()

    def target_file_exits(self, target_file: str) -> Tuple[bool, str]:
        try:
            executor = self._get_ssh_executor()
            executor.open()
            result, err = executor.path_exists(target_file)
            return result, err
        except RuntimeError:
            print(traceback.format_exc(), flush=True)
            return False, "SSH connection failed"
        except Exception as e:
            print(traceback.format_exc(), flush=True)
            return False, str(e)

    def create_dir(self, path: str) -> Tuple[bool, str]:
        try:
            executor = self._get_ssh_executor()
            executor.open()
            result, err = executor.create_dir(path)
            return result, err
        except RuntimeError:
            print(traceback.format_exc())
            return False, "SSH connection failed"
        except Exception as e:
            return False, str(e)

    def upload_file(self, filename: str, target_path: str, mode: str = "cover",
                    call_log: Callable[[int, str], None] = None) -> str:

        if not os.path.isfile(filename):
            return "File: {} does not exist".format(filename)

        target_file = os.path.join(target_path, os.path.basename(filename))
        path_info = self.path_info(target_file)
        if isinstance(path_info, str):
            return path_info

        if path_info['exists'] and mode == "ignore":
            call_log(0, "File upload:{} -> {},The target file already exists, skip uploading".format(filename, target_file))
            return ""
        if path_info['exists'] and mode == "rename":
            upload_name = "{}_{}".format(os.path.basename(filename), public.md5(filename))
            call_log(0, "File upload:{} -> {},The target file already exists, it will be renamed to {}".format(filename, target_file, upload_name))
        else:
            upload_name = os.path.basename(filename)

        try:
            executor = self._get_ssh_executor()
            executor.open()
            def progress_callback(current_size: int, total_size: int):
                if total_size == 0:
                    return
                call_log(current_size * 100 // total_size, "" )
            executor.upload(filename, os.path.join(target_path, upload_name), progress_callback=progress_callback)
        except RuntimeError:
            print(traceback.format_exc(), flush=True)
            return "SSH connection failed"
        except Exception as e:
            print(traceback.format_exc(), flush=True)
            return str(e)
        return ""

    def upload_dir_check(self, target_file: str) -> str:
        try:
            executor = self._get_ssh_executor()
            executor.open()
            path_info = executor.path_info(target_file)
            if not path_info['exists']:
                return ""
            if path_info['is_dir']:
                return "The name path is not a directory"
            return ""
        except RuntimeError:
            print(traceback.format_exc(), flush=True)
            return "SSH connection failed"
        except Exception as e:
            print(traceback.format_exc(), flush=True)
            return str(e)

    def path_info(self, path: str) -> Union[str, Dict]:
        try:
            executor = self._get_ssh_executor()
            executor.open()
            path_info = executor.path_info(path)
            return path_info
        except RuntimeError as e:
            print(traceback.format_exc(), flush=True)
            return "SSH connection failed: {}".format(str(e))
        except Exception as e:
            print(traceback.format_exc(), flush=True)
            return "Failed to obtain path information:{}".format(str(e))
