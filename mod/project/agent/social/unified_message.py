from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class UnifiedMessage:
    """归一化消息模型, 所有平台适配器输出此格式"""
    message_id: str
    platform: str
    account_id: str
    conversation_id: str
    sender_id: str
    sender_name: str
    content: str
    content_type: str = "text"
    timestamp: int = 0
    reply_to: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def session_key(self) -> str:
        """生成 Agent session_id, 格式: social:platform:account_id:conversation_id:sender_id"""
        return f"social:{self.platform}:{self.account_id}:{self.conversation_id}:{self.sender_id}"

    def is_group_message(self) -> bool:
        """判断是否为群聊/频道消息"""
        return self.conversation_id != self.sender_id


@dataclass
class SendResult:
    """消息发送结果"""
    ok: bool
    platform: str
    account_id: str
    target_id: str
    message_id: str = ""
    error: str = ""
    raw: Optional[Dict[str, Any]] = None


def build_message_key(platform: str, account_id: str, conversation_id: str, message_id: str) -> str:
    """构建消息去重key"""
    return f"{platform}:{account_id}:{conversation_id}:{message_id}"