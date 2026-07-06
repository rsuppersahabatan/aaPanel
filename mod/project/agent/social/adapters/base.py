from dataclasses import dataclass
from typing import Any, Callable, Dict

from mod.project.agent.social.unified_message import UnifiedMessage, SendResult


@dataclass
class ConnectionCheckResult:
    """连接检查结果"""
    ok: bool
    message: str = ""
    details: Dict[str, Any] = None


class BaseSocialAdapter:
    """社交平台适配器基类, 使用 asyncio 管理连接"""

    platform: str

    async def start(self, account_config: Dict, message_handler: Callable[[UnifiedMessage], None]):
        """异步启动适配器, 建立连接并开始接收消息"""
        raise NotImplementedError

    async def stop(self):
        """异步停止适配器, 断开连接"""
        raise NotImplementedError

    async def send_message(self, account_config: Dict, target: str, content: str) -> SendResult:
        """异步发送消息到平台"""
        raise NotImplementedError

    async def send_typing(self, account_config: Dict, target: str) -> bool:
        """异步发送平台原生 typing/chat action 状态, 默认不支持"""
        return False

    def check_connection(self, account_config: Dict) -> ConnectionCheckResult:
        """同步检查账号连接性, 测试 token/secret 是否有效"""
        raise NotImplementedError

    def is_running(self) -> bool:
        """检查适配器是否在运行"""
        return False