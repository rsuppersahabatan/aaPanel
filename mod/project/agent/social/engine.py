import json
from typing import Callable, Optional

from mod.project.agent.social.unified_message import UnifiedMessage


class SocialEngine:
    """社交对话引擎, 封装 comMod._chat_generator"""

    def __init__(self, com_mod=None):
        self._com_mod = com_mod

    def reply(
            self,
            message: UnifiedMessage,
            on_stage: Optional[Callable[[str, str], None]] = None,
            cancel_event=None,
            account_config: dict = None,
    ) -> str:
        """
        处理社交消息, 依据 SSE 事件阶段调用 on_stage 回调

        on_stage(stage, content):
          ("thinking",  "🤔 思考中...")  - 首次 message_think
          ("tool_call", "🔧 {name}")     - 每次 tool_call
          ("reply",     content)          - message_end 时发送累积正文
          ("error",     error_text)       - error 事件
        """
        if not self._com_mod:
            from mod.project.agent.comMod import main as ComModMain
            self._com_mod = ComModMain()
        self._com_mod.refresh_runtime_state()

        account_config = account_config or {}
        get = {
            "message": message.content,
            "session_id": message.session_key,
            "prompt_id": "social_chat",
            "smartMode": account_config.get("smart_mode") or "0",
            "account_name": account_config.get("account_name") or "default",
            "model": account_config.get("model") or "qwen3.5-flash",
        }

        accumulated = ""
        thinking_sent = False
        gen = self._com_mod._chat_generator(get)

        try:
            for sse_text in gen:
                if self._is_cancelled(cancel_event):
                    return accumulated.strip()

                event_type, data = self._parse_sse(sse_text)
                if not event_type:
                    continue

                if event_type == "message_think":
                    if not thinking_sent:
                        thinking_sent = True
                        self._emit_stage(on_stage, cancel_event, "thinking", "🤔 Thinking...")

                elif event_type == "tool_call":
                    tool_name = data.get("tool", "Tool") if isinstance(data, dict) else "Tool"
                    self._emit_stage(on_stage, cancel_event, "tool_call", f"🔧 {tool_name}")

                elif event_type == "message":
                    chunk = data if isinstance(data, str) else data.get("response", "")
                    accumulated += chunk

                elif event_type == "error":
                    error_msg = data.get("msg", data) if isinstance(data, dict) else data
                    error_text = f"Error: {error_msg}"
                    self._emit_stage(on_stage, cancel_event, "error", error_text)
                    return error_text

                elif event_type == "message_end":
                    break

            if accumulated.strip() and not self._is_cancelled(cancel_event):
                self._emit_stage(on_stage, cancel_event, "reply", accumulated.strip())

            return accumulated.strip()
        finally:
            close = getattr(gen, "close", None)
            if close:
                try:
                    close()
                except Exception:
                    pass

    def _emit_stage(self, on_stage: Optional[Callable[[str, str], None]], cancel_event, stage: str, content: str):
        """未取消时发送阶段消息"""
        if on_stage and not self._is_cancelled(cancel_event):
            on_stage(stage, content)

    def _is_cancelled(self, cancel_event) -> bool:
        """判断当前回复是否已取消"""
        return bool(cancel_event and cancel_event.is_set())

    def _parse_sse(self, sse_text: str) -> tuple:
        """解析 SSE 文本, 返回 (event_type, data)"""
        if not sse_text.startswith("event: "):
            return None, None

        lines = sse_text.split("\n")
        event_type = None
        data = None

        for line in lines:
            if line.startswith("event: "):
                event_type = line[7:]
            elif line.startswith("data: "):
                data_str = line[6:]
                # SSE 转义换行反转义
                data_str = data_str.replace('\\n', '\n')
                if event_type in ("message", "message_think"):
                    data = data_str
                    continue
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    data = data_str

        return event_type, data
