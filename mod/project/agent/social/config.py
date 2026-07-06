import copy
import json
import os
import shutil
import uuid
from typing import Any, Dict

SECRET_FIELDS = {"bot_token"}
PLATFORM_ALLOWED_FIELDS = {
    "telegram": {"allowed_chat_ids", "allowed_user_ids"},
    "discord": {"allowed_guild_ids", "allowed_channel_ids"},
}
ACCOUNT_FIELDS = {
    "id",
    "platform",
    "bot_token",
    "account_name",  # AI 模型账号名 (对应 models 下的 key)
    "model",  # AI 模型名称
    "smart_mode",  # 智能模式 0=普通 1=全部工具
    "allowed_chat_ids",  # Telegram 聊天白名单
    "allowed_user_ids",  # Telegram 用户白名单
    "allowed_guild_ids",  # Discord 服务器白名单
    "allowed_channel_ids",  # Discord 频道白名单
}

ACCOUNT_DEFAULTS = {
    "account_name": "default",
    "model": "qwen3.5-flash",
    "smart_mode": "0",
    "allowed_chat_ids": [],
    "allowed_user_ids": [],
    "allowed_guild_ids": [],
    "allowed_channel_ids": [],
}

DEFAULT_CONFIG = {
    "version": 1,
    "accounts": [],
}


class SocialConfigStore:
    """社交账号配置存储器, 支持读写social_accounts.json并自动脱敏密钥字段"""

    def __init__(self, file_path: str):
        """初始化配置存储器"""
        self.file_path = file_path

    def load(self) -> Dict[str, Any]:
        """加载配置, 文件不存在或损坏时写入默认配置"""
        if not os.path.exists(self.file_path):
            config = copy.deepcopy(DEFAULT_CONFIG)
            self.save(config)
            return config
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if self._is_structurally_invalid(data):
                raise ValueError("invalid social config structure")
            return self._normalize_config(data)
        except Exception:
            config = copy.deepcopy(DEFAULT_CONFIG)
            self.save(config)
            return config

    def load_runtime(self) -> Dict[str, Any]:
        """加载运行时配置, 账号会补齐默认值"""
        config = self.load()
        runtime = copy.deepcopy(config)
        runtime["accounts"] = [self.with_account_defaults(account) for account in config.get("accounts", [])]
        return runtime

    def save(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """保存配置到文件"""
        normalized = self._normalize_config(config)
        parent = os.path.dirname(self.file_path)
        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)
        tmp_path = f"{self.file_path}.tmp.{os.getpid()}.{uuid.uuid4().hex}"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._compact_config(normalized), f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.file_path)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        return normalized

    def get_config(self, masked: bool = True) -> Dict[str, Any]:
        """获取配置, masked=True时密钥字段脱敏"""
        config = self.load()
        if not masked:
            return config
        return self.mask_config(config)

    def save_account(self, account: Dict[str, Any]) -> Dict[str, Any]:
        """保存或更新账号配置, 验证连接性"""
        account_id = str(account.get("id", "")).strip()
        if not account_id:
            raise ValueError("account id is required")
        platform = str(account.get("platform", "")).strip()
        if platform not in ("telegram", "discord"):
            raise ValueError("platform must be telegram or discord")

        config = self.load()
        accounts = config["accounts"]
        existing = None
        existing_index = -1
        for index, item in enumerate(accounts):
            if item.get("id") == account_id:
                existing = item
                existing_index = index
                break

        # 清洗用户输入, 用于连接测试和新建账号
        clean = self._sanitize_account(account)
        # 记录用户实际传入了哪些字段, 用于区分"没传"和"传了默认值"
        provided_keys = set(account.keys())

        # 构建连接测试数据
        test_data = clean.copy()
        if existing:
            for key in SECRET_FIELDS:
                if key in test_data and self._is_masked_secret(test_data[key]):
                    if key in existing:
                        test_data[key] = existing[key]
                    else:
                        test_data.pop(key, None)
            # 用户没传 token 时用已有的 token 补齐
            if "bot_token" not in provided_keys and "bot_token" in existing:
                test_data["bot_token"] = existing["bot_token"]

        # 仅当用户提供了新 token (非脱敏值) 或新建账号时做连接测试
        token_changed = (
            "bot_token" in provided_keys
            and not self._is_masked_secret(str(account.get("bot_token", "")))
        )
        if (not existing) or token_changed:
            if platform == "telegram":
                from mod.project.agent.social.adapters.telegram import TelegramAdapter
                adapter = TelegramAdapter()
            else:
                from mod.project.agent.social.adapters.discord import DiscordAdapter
                adapter = DiscordAdapter()
            result = adapter.check_connection(test_data)
            if not result.ok:
                raise ValueError(f"Connection failed: {result.message}")

        # 持久化
        if existing is not None:
            merged = existing.copy()
            platform_allowed = PLATFORM_ALLOWED_FIELDS.get(platform, set())
            for key in provided_keys:
                if key not in ACCOUNT_FIELDS or key in ("id", "platform"):
                    continue
                # 跳过不属于当前平台的白名单字段
                if key.startswith("allowed_") and key not in platform_allowed:
                    continue
                value = account.get(key)
                # allowed_* 字段: str 尝试解析为 list
                if key.startswith("allowed_") and isinstance(value, str):
                    try:
                        value = json.loads(value)
                    except (json.JSONDecodeError, ValueError):
                        continue
                # 脱敏密钥, 保留已有值
                if key in SECRET_FIELDS and self._is_masked_secret(value):
                    continue
                if self._is_default_or_empty(key, value):
                    merged.pop(key, None)  # 用户传了空/默认值, 清除该字段
                else:
                    merged[key] = value  # 用户传了有效值, 更新
            # 补齐 STORE_ALWAYS_FIELDS (用户清除后回填默认值)
            for key in self.STORE_ALWAYS_FIELDS:
                if key not in merged or merged[key] is None:
                    merged[key] = ACCOUNT_DEFAULTS.get(key, "")
            accounts[existing_index] = self._sanitize_account(merged)
            self.save(config)
            return accounts[existing_index]
        accounts.append(clean)
        self.save(config)
        return clean

    def delete_account(self, account_id: str) -> bool:
        """删除指定账号"""
        config = self.load()
        accounts = config["accounts"]
        kept = [item for item in accounts if item.get("id") != account_id]
        if len(kept) == len(accounts):
            return False
        config["accounts"] = kept
        self.save(config)
        return True

    def mask_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """对配置中所有账号的密钥字段进行脱敏"""
        masked = copy.deepcopy(config)
        for account in masked.get("accounts", []):
            for field in SECRET_FIELDS:
                if field in account:
                    account[field] = self.mask_secret(account.get(field, ""))
        return masked

    @staticmethod
    def mask_secret(value: Any) -> str:
        """脱敏密钥字符串, 保留前4后4字符"""
        text = "" if value is None else str(value)
        if not text:
            return ""
        if len(text) <= 8:
            return "****"
        return f"{text[:4]}****{text[-4:]}"

    @staticmethod
    def _is_masked_secret(value: Any) -> bool:
        return isinstance(value, str) and "****" in value

    def _is_structurally_invalid(self, data: Any) -> bool:
        if not isinstance(data, dict):
            return True
        if "global" in data and not isinstance(data.get("global"), dict):
            return True
        if "accounts" in data and not isinstance(data.get("accounts"), list):
            return True
        return False

    def _normalize_config(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """规范化配置结构, 补齐缺失字段"""
        config = copy.deepcopy(DEFAULT_CONFIG)
        if isinstance(data, dict):
            config["version"] = int(data.get("version", 1) or 1)
            accounts = data.get("accounts", [])
            if isinstance(accounts, list):
                config["accounts"] = [
                    self._sanitize_account(item)
                    for item in accounts
                    if isinstance(item, dict) and item.get("id") and item.get("platform") in ("telegram", "discord")
                ]
        return config

    def _compact_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """移除落盘配置中的默认字段"""
        compact = {"version": config.get("version", 1), "accounts": config.get("accounts", [])}
        return compact

    def get_runtime_account(self, account_id: str) -> Dict[str, Any]:
        """获取补齐默认值后的账号配置"""
        for account in self.load().get("accounts", []):
            if account.get("id") == account_id:
                return self.with_account_defaults(account)
        return {}

    def with_account_defaults(self, account: Dict[str, Any]) -> Dict[str, Any]:
        """补齐账号运行时默认值"""
        runtime = copy.deepcopy(ACCOUNT_DEFAULTS)
        runtime.update(account)
        return runtime

    # 落盘时始终保留的字段, 即使为空也写入
    STORE_ALWAYS_FIELDS = {"id", "platform", "account_name", "model", "smart_mode"}

    def _sanitize_account(self, account: Dict[str, Any]) -> Dict[str, Any]:
        """清洗账号字段, 根据平台过滤allowed_*白名单, STORE_ALWAYS_FIELDS始终保留"""
        clean = {}
        platform = account.get("platform", "")
        platform_allowed = PLATFORM_ALLOWED_FIELDS.get(platform, set())
        for key in ACCOUNT_FIELDS:
            if key not in account:
                continue
            # 跳过不属于当前平台的白名单字段
            if key.startswith("allowed_") and key not in platform_allowed:
                continue
            value = account[key]
            # allowed_* 字段: str则json.loads, 解析失败则抛弃
            if key.startswith("allowed_") and isinstance(value, str):
                try:
                    value = json.loads(value)
                except (json.JSONDecodeError, ValueError):
                    continue
            if key in self.STORE_ALWAYS_FIELDS:
                clean[key] = value
            elif not self._is_default_or_empty(key, value):
                clean[key] = value
        # 补齐 STORE_ALWAYS_FIELDS 的缺失字段
        for key in self.STORE_ALWAYS_FIELDS:
            if key not in clean:
                clean[key] = ACCOUNT_DEFAULTS.get(key, "")
        return clean

    @staticmethod
    def _is_default_or_empty(key: str, value: Any) -> bool:
        if value is None or value == "" or value == [] or value == {}:
            return True
        if key in ACCOUNT_DEFAULTS and value == ACCOUNT_DEFAULTS[key]:
            return True
        return False


def cleanup_social_sessions(data_path: str, account_id: str, platform: str):
    """清理指定账号的 social 会话目录"""
    sessions_dir = os.path.join(data_path, "social_sessions")
    if not os.path.exists(sessions_dir):
        return

    prefix = f"social:{platform}:{account_id}:"
    for entry in os.listdir(sessions_dir):
        if entry.startswith(prefix):
            session_path = os.path.join(sessions_dir, entry)
            try:
                shutil.rmtree(session_path)
            except Exception:
                pass
