import os
import sys
import threading
import time
from typing import Dict

panel_import_path = os.path.abspath("/www/server/panel")
if panel_import_path not in sys.path:
    sys.path.insert(0, panel_import_path)
try:
    import public
except Exception:
    public = None

from mod.project.agent.social.config import SocialConfigStore, cleanup_social_sessions
from mod.project.agent.social.service import SocialService

try:
    panelPath = os.getenv('BT_PANEL') or (public.get_panel_path() if public else '/www/server/panel')
except Exception:
    panelPath = '/www/server/panel'

APP_DATA_PATH = f'{panelPath}/data/agent'


def return_response(status, msg):
    """统一返回格式, 与 comMod.py 一致"""
    if public:
        if status:
            return public.success_v2(msg)
        return public.fail_v2(msg)
    # 测试环境 fallback
    return {"status": 0 if status else -1, "message": msg, "timestamp": int(time.time())}


class main:
    """社交账号管理 API 门面"""

    _service: SocialService = None
    _service_lock = threading.Lock()  # 防止并发重载服务

    def __init__(self, data_path: str = None):
        self.data_path = data_path or APP_DATA_PATH
        self.config_path = os.path.join(self.data_path, 'social_accounts.json')
        self.store = SocialConfigStore(self.config_path)

    def get_config(self, get):
        """获取脱敏后的社交账号配置"""
        return return_response(True, self.store.get_config(masked=True))

    def save_account(self, get):
        """保存或更新社交账号配置, 成功后异步重载服务"""
        try:
            account = self.store.save_account(self._to_dict(get))
        except Exception as e:
            return return_response(False, str(e))
        # 保存成功异步重载服务
        threading.Thread(target=self._ensure_service_running, daemon=True).start()
        public.set_module_logs("mod_agent_social_app_add", account.get("platform", "unknow"), 1)
        return return_response(True, self.store.mask_config({"accounts": [account]})["accounts"][0])

    def delete_account(self, get):
        """删除指定社交账号"""
        account_id = self._get_value(get, "id") or self._get_value(get, "account_id")
        if not account_id:
            return return_response(False, "account id is required")
        # 获取账号信息用于清理会话
        account = self.store.get_runtime_account(str(account_id))
        platform = account.get("platform", "")
        removed = self.store.delete_account(str(account_id))
        if removed:
            # 清理该账号的会话目录
            cleanup_social_sessions(self.data_path, str(account_id), platform)
            # 无剩余账号则停止服务, 否则重载以移除已删除的适配器
            remaining = self.store.load().get("accounts", [])
            if not remaining:
                self.stop_service({})
            else:
                self._ensure_service_running()
        return return_response(removed, "deleted" if removed else "account not found")

    def start_service(self, get):
        """启动社交服务"""
        if self._service and self._service.status().get("running"):
            return return_response(True, "already running")
        try:
            sessions_dir = os.path.join(self.data_path, "social_sessions")
            self._service = SocialService(self.config_path, sessions_dir)
            self._service.start()
            return return_response(True, "service started")
        except Exception as e:
            return return_response(False, str(e))

    def stop_service(self, get):
        """停止社交服务, 通过 PID 文件和进程名双重清理"""
        import signal as _signal
        # 1. 按 PID 文件停止
        sessions_dir = os.path.join(self.data_path, "social_sessions")
        pid_file = os.path.join(sessions_dir, "social_service.pid")
        if os.path.exists(pid_file):
            try:
                with open(pid_file, "r") as f:
                    pid = int(f.read().strip())
                try:
                    os.kill(pid, _signal.SIGTERM)
                except (ProcessLookupError, OSError):
                    pass
                for _ in range(10):
                    try:
                        os.kill(pid, 0)
                        time.sleep(0.5)
                    except (ProcessLookupError, OSError):
                        break
                try:
                    os.kill(pid, getattr(_signal, "SIGKILL", _signal.SIGTERM))
                except (ProcessLookupError, OSError):
                    pass
            except (ValueError, OSError):
                pass
            if os.path.exists(pid_file):
                os.remove(pid_file)
        # 2. 按进程名杀死所有残留 runner 进程
        try:
            os.system("pkill -f '/www/server/panel/mod/project/agent/social/runner.py' 2>/dev/null")
        except Exception:
            pass

        return return_response(True, "service stopped")


    def status(self, get):
        """获取服务状态"""
        sessions_dir = os.path.join(self.data_path, "social_sessions")
        pid_file = os.path.join(sessions_dir, "social_service.pid")
        running = False
        pid = None
        if os.path.exists(pid_file):
            try:
                with open(pid_file, "r") as f:
                    pid = int(f.read().strip())
                os.kill(pid, 0)
                running = True
            except (ValueError, ProcessLookupError, OSError):
                running = False
                pid = None
        return return_response(True, {"running": running, "pid": pid})

    def reload_service(self, get):
        """重载服务以应用新配置"""
        # 先停止服务
        stop_result = self.stop_service(get)
        if stop_result.get("status") != 0:
            return return_response(False, f"stop failed: {stop_result.get('message')}")

        # 等待进程完全退出
        import time
        time.sleep(1)

        # 重新启动服务
        start_result = self.start_service(get)
        if start_result.get("status") != 0:
            return return_response(False, f"start failed: {start_result.get('message')}")

        return return_response(True, "service reloaded")

    def check_connection(self, get):
        """检查账号连接性"""
        account_id = self._get_value(get, "id") or self._get_value(get, "account_id")
        if not account_id:
            return return_response(False, "account id is required")
        if not self._service:
            # 直接测试连接
            config = self.store.load_runtime()
            account = self._find_account(config, account_id)
            if not account:
                return return_response(False, "account not found")
            from mod.project.agent.social.service import SocialService
            adapter = SocialService(self.config_path, "")._create_adapter(account.get("platform"))
            if not adapter:
                return return_response(False, "unsupported platform")
            check_result = adapter.check_connection(account)
            return return_response(check_result.ok, {"message": check_result.message, "details": check_result.details})
        check_result = self._service.check_connection(account_id)
        return return_response(check_result.ok, {"message": check_result.message, "details": check_result.details})

    def test_send(self, get):
        """测试发送消息"""
        import asyncio
        account_id = self._get_value(get, "id") or self._get_value(get, "account_id")
        target = self._get_value(get, "target") or self._get_value(get, "chat_id") or self._get_value(get, "channel_id")
        text = self._get_value(get, "text") or "aaPanel social bot test"
        if not target:
            return return_response(False, "target is required")
        config = self.store.load_runtime()
        account = self._find_account(config, account_id)
        if not account:
            return return_response(False, "account not found")
        adapter = SocialService(self.config_path, "")._create_adapter(account.get("platform"))
        if not adapter:
            return return_response(False, "unsupported platform")
        # 使用 asyncio 发送
        try:
            loop = asyncio.new_event_loop()
            send_result = loop.run_until_complete(adapter.send_message(account, target, text))
            loop.close()
            return return_response(send_result.ok, {"message": send_result.error or "sent", "message_id": send_result.message_id})
        except Exception as e:
            return return_response(False, str(e))

    def webhook(self, get):
        """HTTP 回调入口 (Telegram/Discord 不使用 HTTP 回调, 此方法保留兼容)"""
        return return_response(False, "Telegram/Discord do not support HTTP webhook, use long polling or WebSocket instead")

    def reload_config(self, get):
        """重新加载配置"""
        if self._service:
            self._service.reload_config()
        return return_response(True, "config reloaded")

    def _ensure_service_running(self):
        """确保服务运行: 已运行则重载, 未运行则启动, 加锁防止并发"""
        with self._service_lock:
            self.stop_service({})
            time.sleep(1)
            self.start_service({})

    def _find_account(self, config: Dict, account_id: str):
        for account in config.get("accounts", []):
            if account.get("id") == account_id:
                return account
        return None

    @staticmethod
    def _to_dict(get) -> Dict:
        if isinstance(get, dict):
            return dict(get)
        data = {}
        for key in dir(get):
            if key.startswith("_"):
                continue
            try:
                value = getattr(get, key)
            except Exception:
                continue
            if not callable(value):
                data[key] = value
        return data

    @staticmethod
    def _get_value(get, key: str):
        if isinstance(get, dict):
            return get.get(key)
        return getattr(get, key, None)
