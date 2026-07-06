import json
import os
import time
import uuid
import public
from typing import List, Dict, Any, Union


class MemoryManager:
    def __init__(self, session_id: str, sessions_dir: str = "sessions", sliding_window_size: int = 10,
                 model_name: str = None):
        self.session_id = session_id
        self.sliding_window_size = sliding_window_size
        self.model_name = model_name
        self.session_dir = os.path.join(sessions_dir, session_id)
        self.file_path = os.path.join(self.session_dir, "sessions.json")
        self.meta_file_path = os.path.join(self.session_dir, "meta.json")
        self.history: List[Dict[str, Any]] = []
        self._ensure_sessions_dir()
        self.load_session()
        self._load_or_create_meta()

    def _ensure_sessions_dir(self):
        if not os.path.exists(self.session_dir):
            try:
                os.makedirs(self.session_dir, exist_ok=True)
            except OSError as e:
                public.print_log(f"[ERROR] Failed to create session directory {self.session_dir}: {str(e)}")
                raise

    def _load_or_create_meta(self):
        from mod.project.agent.chat_client.tools.base import atomic_update_json

        def _m(d):
            # 不存在/空: 初始化
            if not d:
                return {
                    "session_id": self.session_id,
                    "model_name": self.model_name,
                    "created_at": time.time(),
                    "total_tokens": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                }
            # 存在: 迁移, 无变化则跳过(返回 None 不写)
            changed = False
            if self.model_name and d.get("model_name") != self.model_name:
                d["model_name"] = self.model_name
                changed = True
            if "total_tokens" not in d:
                d["total_tokens"] = 0
                d["input_tokens"] = 0
                d["output_tokens"] = 0
                changed = True
            return d if changed else None

        ok, msg = atomic_update_json(self.meta_file_path, _m)
        if not ok:
            public.print_log(f"[ERROR] Failed to init/update meta file {self.meta_file_path}: {msg}")
            raise RuntimeError(f"meta init/update failed: {msg}")

    def update_meta_tokens(self, total_tokens: int, input_tokens: int, output_tokens: int):
        from mod.project.agent.chat_client.tools.base import atomic_update_json

        def _m(d):
            if not d:  # 文件不存在/空, 兜底初始化
                d = {"session_id": self.session_id, "created_at": time.time()}
            d["total_tokens"] = total_tokens
            d["input_tokens"] = input_tokens
            d["output_tokens"] = output_tokens
            d["updated_at"] = time.time()
            return d

        try:
            atomic_update_json(self.meta_file_path, _m)
        except Exception as e:
            public.print_log(f"[ERROR] update_meta_tokens failed: {str(e)}")

    def load_session(self):
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    self.history = json.load(f)
            except Exception as e:
                self.history = []
        else:
            self.history = []

    def save_session(self):
        try:
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump(self.history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            pass

    def add_message(self, role: str, content: Union[str, List[Dict[str, Any]]], id: str = None, **kwargs):
        msg = {
            "id": id if id else str(uuid.uuid4()),
            "role": role,
            "content": content,
            "timestamp": time.time(),
            **kwargs
        }
        self.history.append(msg)
        self.save_session()
        return msg

    def _split_into_rounds(self) -> List[List[Dict[str, Any]]]:
        """
        将历史消息分割为对话轮次。
        一轮对话定义为：从一个 'user' 消息开始，包含随后的所有 'assistant'/'tool' 消息，
        直到遇到下一个 'user' 消息或历史结束。
        """
        rounds = []
        current_round = []

        for msg in self.history:
            # 过滤掉 reasoning_content
            clean_msg = msg.copy()
            # if "reasoning_content" in clean_msg:
            # del clean_msg["reasoning_content"]

            if clean_msg['role'] == 'user':
                if current_round:
                    rounds.append(current_round)
                current_round = [clean_msg]
            else:
                # 兼容性：如果历史记录不是以 user 开头（罕见），也归入当前轮次（或创建新轮次）
                if not current_round and not rounds:
                    # 孤立的非 user 消息，作为第一轮
                    current_round = [clean_msg]
                else:
                    current_round.append(clean_msg)

        if current_round:
            rounds.append(current_round)

        return rounds

    def get_sliding_window(self) -> List[Dict[str, Any]]:
        """
        返回最后 N 轮对话中的所有消息。
        配置项 SLIDING_WINDOW_SIZE 现在表示轮次数，而非单条消息数。
        """
        rounds = self._split_into_rounds()

        # 获取最后 N 轮
        last_n_rounds = rounds[-self.sliding_window_size:]

        # 展平为消息列表
        window_messages = []
        for r in last_n_rounds:
            window_messages.extend(r)

        return window_messages

    def get_dynamic_window(self, token_budget: int, estimator) -> List[Dict[str, Any]]:
        """按 token 预算从最新轮向前选择历史窗口。"""
        rounds = self._split_into_rounds()
        if not rounds or token_budget <= 0:
            return self.get_sliding_window()

        selected_rounds = []
        used_tokens = 0

        for round_msgs in reversed(rounds):
            round_tokens = estimator(round_msgs)
            if selected_rounds and used_tokens + round_tokens > token_budget:
                break
            selected_rounds.append(round_msgs)
            used_tokens += round_tokens
            if used_tokens >= token_budget:
                break

        if not selected_rounds:
            selected_rounds.append(rounds[-1])

        window_messages = []
        for r in reversed(selected_rounds):
            window_messages.extend(r)
        return window_messages

    def get_full_history(self) -> List[Dict[str, Any]]:
        return self.history

    def get_total_rounds(self) -> int:
        return len(self._split_into_rounds())

    def get_message_rounds(self) -> int:
        """
        获取当前对话轮数
        Returns:
            int: 对话轮次数量
        """
        return len(self._split_into_rounds())

    def compact_messages(self, summary_msg: Dict, messages_to_keep: List) -> None:
        """
        执行消息压缩，将历史替换为摘要消息+保留的最近消息
        压缩后结构：[summary_msg, ...messages_to_keep]
        Args:
            summary_msg: 压缩摘要消息字典，role为user，包含历史摘要
            messages_to_keep: 需要保留的最近消息列表（最后N轮对话）
        """
        self.history = [summary_msg] + messages_to_keep
        self.save_session()

    def check_auto_compact(self, max_context_tokens: int, threshold_ratio: float = 0.75) -> bool:
        """
        检查是否需要自动压缩（预留方法，当前不启用）
        Args:
            max_context_tokens: 最大上下文token数
            threshold_ratio: 触发压缩的阈值比例（已使用token / 最大token）
        Returns:
            bool: 是否需要压缩
        Note: 此方法当前仅作为预留入口，自动压缩功能未启用
        """
        # 自动压缩功能当前未启用，此方法仅作为预留代码位置
        # 如需实现，可使用 Agent._estimate_messages_tokens 进行 token 估算
        return False
