import os
import subprocess
import time
import signal

from typing import Any, Dict, Optional

from mod.project.agent.social.adapters.base import BaseSocialAdapter, ConnectionCheckResult
from mod.project.agent.social.config import SocialConfigStore


class SocialService:
    """社交服务管理器, 使用独立进程运行"""

    def __init__(self, config_path: str, sessions_dir: str):
        self.config_store = SocialConfigStore(config_path)
        self.sessions_dir = sessions_dir
        self._running = False
        self._process: Optional[subprocess.Popen] = None
        self._pid_file: str = os.path.join(sessions_dir, "social_service.pid")

    def start(self):
        """启动服务进程"""
        if self._running:
            return
        os.makedirs(os.path.dirname(self._pid_file), exist_ok=True)
        if self._check_existing_process():
            self._running = True
            return

        runner_path = os.path.join(os.path.dirname(__file__), "runner.py")
        cmd = [
            "btpython",
            runner_path,
            "--config", self.config_store.file_path,
            "--sessions", self.sessions_dir,
        ]
        self._process = subprocess.Popen(cmd)

        with open(self._pid_file, "w") as f:
            f.write(str(self._process.pid))

        self._running = True
        time.sleep(2)

    def _check_existing_process(self) -> bool:
        """检查是否有已存在的服务进程"""
        if not os.path.exists(self._pid_file):
            return False
        try:
            with open(self._pid_file, "r") as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            return True
        except (ValueError, ProcessLookupError, OSError):
            # 进程不存在，清理 PID 文件
            if os.path.exists(self._pid_file):
                os.remove(self._pid_file)
            return False

    def stop(self):
        """停止服务进程"""
        self._running = False
        if os.path.exists(self._pid_file):
            try:
                with open(self._pid_file, "r") as f:
                    pid = int(f.read().strip())
                os.kill(pid, signal.SIGTERM)
                time.sleep(1)
                try:
                    os.kill(pid, 0)
                    os.kill(pid, getattr(signal, "SIGKILL", signal.SIGTERM))
                except ProcessLookupError:
                    pass
            except (ValueError, ProcessLookupError, OSError):
                pass
            if os.path.exists(self._pid_file):
                os.remove(self._pid_file)

        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=3)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None

    def check_connection(self, account_id: str) -> ConnectionCheckResult:
        """测试账号连接性"""
        config = self.config_store.load_runtime()
        account = self._find_account(config, account_id)
        if not account:
            return ConnectionCheckResult(ok=False, message="account not found")
        adapter = self._create_adapter(account.get("platform"))
        if not adapter:
            return ConnectionCheckResult(ok=False, message="unsupported platform")
        return adapter.check_connection(account)

    def status(self) -> Dict[str, Any]:
        """获取服务状态"""
        running = self._check_existing_process()
        pid = None
        if os.path.exists(self._pid_file):
            try:
                with open(self._pid_file, "r") as f:
                    pid = int(f.read().strip())
            except:
                pass
        return {
            "running": running,
            "pid": pid,
        }

    def reload_config(self):
        """重新加载配置"""
        if os.path.exists(self._pid_file):
            try:
                with open(self._pid_file, "r") as f:
                    pid = int(f.read().strip())
                os.kill(pid, signal.SIGUSR1)
            except Exception:
                pass

    def start_account(self, account_id: str) -> bool:
        """启动指定账号, subprocess 架构下通过重启服务应用配置"""
        config = self.config_store.load_runtime()
        if not self._find_account(config, account_id):
            return False
        self.stop()
        self.start()
        return True

    def stop_account(self, account_id: str) -> bool:
        """停止指定账号, subprocess 架构下通过重启服务应用配置"""
        self.stop()
        self.start()
        return True

    def _find_account(self, config: Dict, account_id: str) -> Optional[Dict]:
        for account in config.get("accounts", []):
            if account.get("id") == account_id:
                return account
        return None

    def _create_adapter(self, platform: str) -> Optional[BaseSocialAdapter]:
        """创建平台适配器"""
        if platform == "telegram":
            from mod.project.agent.social.adapters.telegram import TelegramAdapter
            return TelegramAdapter()
        if platform == "discord":
            from mod.project.agent.social.adapters.discord import DiscordAdapter
            return DiscordAdapter()
        return None