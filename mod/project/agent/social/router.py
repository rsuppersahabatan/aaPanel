import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Set

from mod.project.agent.social.unified_message import UnifiedMessage, build_message_key


DEDUP_TTL_SECONDS = 86400


def _log(msg: str):
    """调试日志"""
    try:
        panel_path = os.getenv("BT_PANEL") or "/www/server/panel"
        log_dir = os.path.join(panel_path, "data", "agent", "logs", "social_logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "router.log")
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {msg}"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


@dataclass
class RouteResult:
    """路由处理结果"""
    allowed: bool
    reason: str = ""
    account: Dict[str, Any] = None
    global_config: Dict[str, Any] = None


class FileDedupStore:
    """基于文件的事件去重存储"""

    def __init__(self, file_path: str, ttl_seconds: int = DEDUP_TTL_SECONDS):
        self.file_path = file_path
        self.ttl_seconds = ttl_seconds
        self._cache: Set[str] = set()
        self._load()

    def _load(self):
        if not os.path.exists(self.file_path):
            return
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            now = int(time.time())
            for key, ts in data.items():
                if now - int(ts) < self.ttl_seconds:
                    self._cache.add(key)
        except Exception:
            self._cache = set()

    def _save(self):
        now = int(time.time())
        data = {key: now for key in self._cache}
        parent = os.path.dirname(self.file_path)
        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception:
            pass

    def contains(self, key: str) -> bool:
        return key in self._cache

    def add(self, key: str):
        self._cache.add(key)
        self._save()


class MessageRouter:
    """消息路由器, 负责去重、白名单、长度校验"""

    def __init__(
        self,
        config: Dict[str, Any],
        dedup_store: Optional[FileDedupStore] = None
    ):
        self.config = config
        self.dedup_store = dedup_store

    def route(self, message: UnifiedMessage) -> RouteResult:
        """校验消息是否允许处理"""
        # 1. 去重检查
        msg_key = build_message_key(message.platform, message.account_id, message.conversation_id, message.message_id)
        if self.dedup_store and self.dedup_store.contains(msg_key):
            return RouteResult(allowed=False, reason="duplicate")

        if self.dedup_store:
            self.dedup_store.add(msg_key)

        # 2. 全局启用检查
        global_config = self.config.get("global", {})
        if not global_config.get("enabled", True):
            return RouteResult(allowed=False, reason="disabled globally", global_config=global_config)

        # 3. 查找账号配置
        account = self._find_account(message.account_id, message.platform)
        if not account:
            return RouteResult(allowed=False, reason="account not found", global_config=global_config)

        if not account.get("enabled", True):
            return RouteResult(allowed=False, reason="account disabled", account=account, global_config=global_config)

        # 4. 白名单校验
        if not self._is_allowed_source(message, account):
            return RouteResult(allowed=False, reason="source not allowed", account=account, global_config=global_config)

        # 5. 消息长度校验
        max_len = int(global_config.get("max_message_length", 4000) or 4000)
        if len(message.content) > max_len:
            return RouteResult(allowed=False, reason="message too long", account=account, global_config=global_config)

        # 6. 允许处理
        return RouteResult(allowed=True, reason="ok", account=account, global_config=global_config)

    def _find_account(self, account_id: str, platform: str) -> Optional[Dict[str, Any]]:
        for account in self.config.get("accounts", []):
            if account.get("id") == account_id and account.get("platform") == platform:
                return account
        return None

    def _is_allowed_source(self, message: UnifiedMessage, account: Dict[str, Any]) -> bool:
        """检查消息来源是否在白名单, 无配置时放行"""
        # allowed_user_ids: 通用用户白名单
        allowed_users = _string_set(account.get("allowed_user_ids", []))
        if allowed_users and message.sender_id not in allowed_users:
            _log(f"[allow] user rejected: sender_id={message.sender_id}, allowed_users={allowed_users}")
            return False

        if message.platform == "telegram":
            allowed_chats = _string_set(account.get("allowed_chat_ids", []))
            if not allowed_chats:
                return True
            ok = message.conversation_id in allowed_chats
            _log(f"[allow] telegram: chat_id={message.conversation_id}, allowed={allowed_chats}, ok={ok}")
            return ok

        if message.platform == "discord":
            allowed_channels = _string_set(account.get("allowed_channel_ids", []))
            allowed_guilds = _string_set(account.get("allowed_guild_ids", []))
            if not allowed_channels and not allowed_guilds:
                return True
            channel_ok = allowed_channels and message.conversation_id in allowed_channels
            guild_id = message.raw.get("guild_id") if isinstance(message.raw, dict) else None
            guild_ok = allowed_guilds and guild_id in allowed_guilds
            ok = (channel_ok and guild_ok) if (allowed_channels and allowed_guilds) else (channel_ok or guild_ok)
            _log(f"[allow] discord: channel={message.conversation_id}, guild_id={guild_id}, "
                 f"allowed_channels={allowed_channels}, allowed_guilds={allowed_guilds}, "
                 f"channel_ok={channel_ok}, guild_ok={guild_ok}, ok={ok}")
            return ok

        return True


def _string_set(items) -> set:
    if not isinstance(items, list):
        return set()
    return {str(item) for item in items if str(item)}