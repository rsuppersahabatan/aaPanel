import asyncio
import json
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


DISCORD_GATEWAY_URL = "wss://gateway.discord.gg/?v=10&encoding=json"
DISCORD_DEFAULT_INTENTS = 512 | 32768  # GUILD_MESSAGES + MESSAGE_CONTENT


def _log(msg: str):
    """调试日志"""
    # try:
    #     panel_path = os.getenv("BT_PANEL") or "/www/server/panel"
    #     log_dir = os.path.join(panel_path, "data", "agent", "logs", "social_logs")
    #     os.makedirs(log_dir, exist_ok=True)
    #     log_file = os.path.join(log_dir, "discord.log")
    #     ts = time.strftime("%Y-%m-%d %H:%M:%S")
    #     line = f"[{ts}] {msg}"
    #     print(line)
    #     with open(log_file, "a", encoding="utf-8") as f:
    #         f.write(line + "\n")
    # except Exception:
    #     print(msg)
    pass


class DiscordAdapter(BaseSocialAdapter):
    """Discord 平台适配器, 使用 WebSocket Gateway 连接"""

    platform = "discord"

    def __init__(self):
        self._ws: Any = None
        self._session: Any = None
        self._running = False
        self._ws_task: asyncio.Task = None
        self._heartbeat_task: asyncio.Task = None
        self._sequence: int = 0
        self._ready = False
        self._config: Dict = None
        self._handler: Callable = None

    async def start(self, account_config: Dict, message_handler: Callable[[UnifiedMessage], None]):
        """启动 WebSocket Gateway 连接"""
        self._config = account_config
        self._handler = message_handler
        self._running = True
        self._session = aiohttp.ClientSession()
        _log("Discord adapter starting...")
        self._ws_task = asyncio.create_task(self._ws_loop())

    async def stop(self):
        """停止 WebSocket 连接"""
        self._running = False
        self._ready = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()
            self._ws = None
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
        if self._session:
            await self._session.close()
            self._session = None

    async def send_message(self, account_config: Dict, target: str, content: str) -> SendResult:
        """发送 Discord 频道消息"""
        token = account_config.get("bot_token", "")
        account_id = account_config.get("id", "")
        url = f"https://discord.com/api/v10/channels/{target}/messages"
        headers = {"Authorization": f"Bot {token}"}
        payload = {"content": content}
        try:
            if not self._session:
                self._session = aiohttp.ClientSession()
            async with self._session.post(url, json=payload, headers=headers) as resp:
                data = await resp.json()
                message_id = str(data.get("id", ""))
                ok = bool(message_id) and resp.status == 200
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
        """发送 Discord typing indicator"""
        token = account_config.get("bot_token", "")
        if not token or not target:
            return False
        url = f"https://discord.com/api/v10/channels/{target}/typing"
        headers = {"Authorization": f"Bot {token}"}
        try:
            if not self._session:
                self._session = aiohttp.ClientSession()
            async with self._session.post(url, headers=headers) as resp:
                return resp.status == 204
        except Exception as e:
            _log(f"Discord typing error: {e}")
            return False

    def check_connection(self, account_config: Dict) -> ConnectionCheckResult:
        """同步检查 Discord bot token 连接性"""
        token = account_config.get("bot_token", "")
        if not token:
            return ConnectionCheckResult(ok=False, message="bot_token is required")
        try:
            resp = requests.get(
                "https://discord.com/api/v10/users/@me",
                headers={"Authorization": f"Bot {token}"},
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                return ConnectionCheckResult(
                    ok=True,
                    message=f"connected to {data.get('username', 'unknown')}",
                    details={"bot_id": data.get("id"), "bot_name": data.get("username")}
                )
            return ConnectionCheckResult(ok=False, message=f"HTTP {resp.status_code}: {resp.text}")
        except Exception as e:
            return ConnectionCheckResult(ok=False, message=str(e))

    def is_running(self) -> bool:
        return self._running and self._ready

    # IDENTIFY 失败的 close code, 遇到这些不再重连
    _AUTH_CLOSE_CODES = {4003, 4004, 4010, 4011, 4012, 4013, 4014}

    async def _ws_loop(self):
        """WebSocket Gateway 主循环"""
        _log("WebSocket loop starting...")
        while self._running:
            try:
                _log(f"Connecting to {DISCORD_GATEWAY_URL}")
                self._ws = await self._session.ws_connect(DISCORD_GATEWAY_URL)
                _log("WebSocket connected")
                close_code = await self._handle_gateway()
                # 认证类错误, 不再重连
                if close_code in self._AUTH_CLOSE_CODES:
                    _log(f"Auth error (code={close_code}), stopping reconnect")
                    self._running = False
                    break
                _log(f"Gateway ended (code={close_code}), reconnecting in 5s")
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                _log("WebSocket loop cancelled")
                break
            except Exception as e:
                _log(f"WebSocket error: {e}, reconnecting in 5s")
                await asyncio.sleep(5)

    async def _handle_gateway(self) -> int:
        """处理 Gateway 消息, 返回 close code"""
        _log("Handling gateway messages...")
        async for msg in self._ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                payload = json.loads(msg.data)
                op = payload.get("op")
                self._sequence = payload.get("s", self._sequence)
                _log(f"Received op={op}")
                if op == 10:  # HELLO
                    interval = payload.get("d", {}).get("heartbeat_interval", 45000) / 1000
                    _log(f"HELLO, heartbeat interval={interval}")
                    self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(interval))
                    await self._identify()
                elif op == 11:  # HEARTBEAT ACK
                    _log("HEARTBEAT ACK")
                elif op == 9:  # INVALID SESSION
                    resumable = payload.get("d", False)
                    _log(f"INVALID SESSION, resumable={resumable}")
                    if not resumable:
                        self._ready = False
                        break
                elif op == 0:  # DISPATCH
                    event = payload.get("t")
                    _log(f"DISPATCH event={event}")
                    if event == "READY":
                        self._ready = True
                        _log("READY, bot is ready!")
                    elif event == "MESSAGE_CREATE":
                        _log("MESSAGE_CREATE received")
                        await self._on_message_create(payload.get("d"))
            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                close_code = getattr(self._ws, "close_code", None)
                _log(f"WebSocket closed/error: type={msg.type}, code={close_code}")
                self._ready = False
                return close_code or -1
        # async for 正常结束, 取 close code
        return getattr(self._ws, "close_code", None) or 0

    async def _identify(self):
        """发送 IDENTIFY payload"""
        token = self._config.get("bot_token", "")
        masked = f"{token[:4]}****{token[-4:]}" if token and len(token) > 8 else "(empty)"
        _log(f"IDENTIFY token={masked}, length={len(token)}")
        intents = int(self._config.get("intents", DISCORD_DEFAULT_INTENTS) or DISCORD_DEFAULT_INTENTS)
        intents |= DISCORD_DEFAULT_INTENTS
        identify = {
            "op": 2,
            "d": {
                "token": token,
                "intents": intents,
                "properties": {"os": "linux", "browser": "aapanel", "device": "aapanel"}
            }
        }
        await self._ws.send_str(json.dumps(identify))

    async def _heartbeat_loop(self, interval: float):
        """心跳循环"""
        while self._running and self._ws:
            try:
                heartbeat = {"op": 1, "d": self._sequence}
                await self._ws.send_str(json.dumps(heartbeat))
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception:
                break

    async def _on_message_create(self, data: Dict):
        """处理 MESSAGE_CREATE 事件"""
        author = data.get("author") or {}
        if author.get("bot"):
            _log("Ignore bot message")
            return
        timestamp = data.get("timestamp") or 0
        try:
            timestamp = int(timestamp)
        except (TypeError, ValueError):
            timestamp = 0
        message = UnifiedMessage(
            message_id=str(data.get("id", "")),
            platform=self.platform,
            account_id=self._config.get("id", ""),
            conversation_id=str(data.get("channel_id", "")),
            sender_id=str(author.get("id", "")),
            sender_name=author.get("username") or "",
            content=data.get("content") or "",
            content_type="text",
            timestamp=timestamp,
            reply_to=str((data.get("message_reference") or {}).get("message_id", "")),
            raw=data
        )
        if not message.content:
            _log(f"MESSAGE_CREATE empty content, channel={message.conversation_id}, sender={message.sender_id}")
            return
        if self._handler:
            self._handler(message)