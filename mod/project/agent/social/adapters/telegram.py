import asyncio
import os
import time
from typing import Any, Callable, Dict

import requests

try:
    import aiohttp
except ImportError:
    os.system("btpip install aiohttp -q")
    import aiohttp

from mod.project.agent.social.adapters.base import BaseSocialAdapter, ConnectionCheckResult
from mod.project.agent.social.unified_message import UnifiedMessage, SendResult


def _log(msg: str):
    """调试日志"""
    # try:
    #     panel_path = os.getenv("BT_PANEL") or "/www/server/panel"
    #     log_dir = os.path.join(panel_path, "data", "agent", "logs", "social_logs")
    #     os.makedirs(log_dir, exist_ok=True)
    #     log_file = os.path.join(log_dir, "telegram.log")
    #     ts = time.strftime("%Y-%m-%d %H:%M:%S")
    #     line = f"[{ts}] {msg}"
    #     print(line)
    #     with open(log_file, "a", encoding="utf-8") as f:
    #         f.write(line + "\n")
    # except Exception:
    #     print(msg)
    pass


class TelegramAdapter(BaseSocialAdapter):
    """Telegram 平台适配器, 使用长轮询获取消息"""

    platform = "telegram"

    def __init__(self):
        self._session: Any = None
        self._running = False
        self._poll_task: asyncio.Task = None
        self._offset = 0
        self._config: Dict = None
        self._handler: Callable = None

    async def start(self, account_config: Dict, message_handler: Callable[[UnifiedMessage], None]):
        """启动长轮询循环"""
        self._session = aiohttp.ClientSession()
        self._running = True
        self._config = account_config
        self._handler = message_handler
        account_id = account_config.get("id", "")
        _log(f"Telegram adapter starting, account={account_id}")
        self._poll_task = asyncio.create_task(self._poll_loop())

    async def stop(self):
        """停止长轮询并关闭连接"""
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        if self._session:
            await self._session.close()
            self._session = None

    async def send_message(self, account_config: Dict, target: str, content: str) -> SendResult:
        """发送 Telegram 消息"""
        token = account_config.get("bot_token", "")
        account_id = account_config.get("id", "")
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": target, "text": content}
        try:
            if not self._session:
                self._session = aiohttp.ClientSession()
            async with self._session.post(url, json=payload) as resp:
                data = await resp.json()
                ok = data.get("ok", False)
                message_id = str((data.get("result") or {}).get("message_id", ""))
                return SendResult(
                    ok=ok,
                    platform=self.platform,
                    account_id=account_id,
                    target_id=target,
                    message_id=message_id,
                    error="" if ok else str(data),
                    raw=data
                )
        except Exception as e:
            return SendResult(ok=False, platform=self.platform, account_id=account_id, target_id=target, error=str(e))

    async def send_typing(self, account_config: Dict, target: str) -> bool:
        """发送 Telegram typing chat action"""
        token = account_config.get("bot_token", "")
        if not token or not target:
            return False
        url = f"https://api.telegram.org/bot{token}/sendChatAction"
        payload = {"chat_id": target, "action": "typing"}
        try:
            if not self._session:
                self._session = aiohttp.ClientSession()
            async with self._session.post(url, json=payload) as resp:
                data = await resp.json()
                return bool(data.get("ok"))
        except Exception:
            return False

    def check_connection(self, account_config: Dict) -> ConnectionCheckResult:
        """同步检查 Telegram bot token 连接性"""
        token = account_config.get("bot_token", "")
        if not token:
            return ConnectionCheckResult(ok=False, message="bot_token is required")
        try:
            resp = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
            data = resp.json()
            if data.get("ok"):
                bot_info = data.get("result", {})
                return ConnectionCheckResult(
                    ok=True,
                    message=f"connected to {bot_info.get('username', 'unknown')}",
                    details={"bot_id": bot_info.get("id"), "bot_name": bot_info.get("first_name")}
                )
            return ConnectionCheckResult(ok=False, message=data.get("description", "unknown error"))
        except Exception as e:
            return ConnectionCheckResult(ok=False, message=str(e))

    def is_running(self) -> bool:
        return self._running and self._poll_task and not self._poll_task.done()

    async def _poll_loop(self):
        """长轮询循环"""
        token = self._config.get("bot_token", "")
        timeout = int(self._config.get("poll_timeout", 30) or 30)
        url = f"https://api.telegram.org/bot{token}/getUpdates"
        _log(f"Poll loop started, timeout={timeout}s")
        while self._running:
            try:
                if not self._session or self._session.closed:
                    self._session = aiohttp.ClientSession()
                params = {"offset": self._offset, "timeout": timeout}
                client_timeout = aiohttp.ClientTimeout(total=timeout + 10)
                async with self._session.get(url, params=params, timeout=client_timeout) as resp:
                    data = await resp.json()
                    if not data.get("ok"):
                        _log(f"Poll error: {data.get('description', 'unknown')}")
                        await asyncio.sleep(5)
                        continue
                    updates = data.get("result", [])
                    for update in updates:
                        self._offset = update.get("update_id", 0) + 1
                        message = self._parse_update(update)
                        if message and message.content:
                            _log(f"Message from {message.sender_name} in chat {message.conversation_id}: {message.content[:80]}")
                            self._handler(message)
            except asyncio.CancelledError:
                _log("Poll loop cancelled")
                break
            except Exception as e:
                _log(f"Poll exception: {type(e).__name__}: {e}")
                await asyncio.sleep(5)

    def _parse_update(self, update: Dict) -> UnifiedMessage:
        """解析 Telegram update 为 UnifiedMessage"""
        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        if sender.get("is_bot"):
            return None
        return UnifiedMessage(
            message_id=str(message.get("message_id") or update.get("update_id") or ""),
            platform=self.platform,
            account_id=self._config.get("id", ""),
            conversation_id=str(chat.get("id", "")),
            sender_id=str(sender.get("id", "")),
            sender_name=sender.get("username") or sender.get("first_name") or "",
            content=message.get("text") or "",
            content_type="text",
            timestamp=int(message.get("date") or 0),
            reply_to=str((message.get("reply_to_message") or {}).get("message_id", "")),
            raw=update
        )