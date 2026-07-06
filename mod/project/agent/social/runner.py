#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""社交服务独立进程入口"""

import argparse
import asyncio
import os
import signal
import sys
import threading
import time
import traceback
from concurrent.futures import TimeoutError
from typing import Dict

# 添加面板路径
panel_path = os.getenv("BT_PANEL") or "/www/server/panel"
class_path = os.path.join(panel_path, "class")
for import_path in (panel_path, class_path):
    if import_path not in sys.path:
        sys.path.insert(0, import_path)

try:
    from public.hook_import import hook_import

    hook_import()
except:
    pass

# 设置日志
log_dir = os.path.join(panel_path, "data", "agent", "logs", "social_logs")
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "service.log")


def log(msg: str):
    """写入日志"""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


log("Social runner starting...")

# 安装依赖
try:
    import aiohttp
except ImportError:
    log("Installing aiohttp...")
    os.system("btpip install aiohttp -q")
    import aiohttp

try:
    from mod.project.agent.social.unified_message import UnifiedMessage
    from mod.project.agent.social.config import SocialConfigStore
    from mod.project.agent.social.router import MessageRouter, FileDedupStore
    from mod.project.agent.social.engine import SocialEngine
except Exception as e:
    log(f"Import error: {e}\n{traceback.format_exc()}")
    sys.exit(1)


class SocialRunner:
    """社交服务运行器"""

    def __init__(self, config_path: str, sessions_dir: str):
        self.config_path = config_path
        self.sessions_dir = sessions_dir
        self.config_store = None
        self._loop = None
        self._adapters = {}
        self._running = False
        self._router = None
        self._engine = None
        self._loop_thread_id = None
        self._interrupt_merge_window_seconds = 0.8
        self._typing_keepalive_interval_seconds = 4.0
        self._session_lock = threading.Lock()
        self._session_states = {}
        self._send_locks = {}
        self._send_locks_lock = threading.Lock()

    def run(self):
        """运行服务"""
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._running = True

            signal.signal(signal.SIGTERM, self._on_shutdown)
            signal.signal(signal.SIGINT, self._on_shutdown)

            log("Initializing...")
            self._init_components()

            config = self.config_store.load_runtime()
            accounts = config.get("accounts", [])
            log(f"Accounts: {len(accounts)}")

            for account in accounts:
                aid = account.get("id")
                plat = account.get("platform")
                log(f"Starting {aid} ({plat})")
                try:
                    self._loop.run_until_complete(self._start_adapter(account))
                except Exception as e:
                    log(f"Adapter {aid} error: {e}\n{traceback.format_exc()}")

            log(f"Ready, adapters: {list(self._adapters.keys())}")
            self._loop_thread_id = threading.get_ident()
            self._loop.run_forever()
        except Exception as e:
            log(f"Run error: {e}\n{traceback.format_exc()}")
            sys.exit(1)

    def _init_components(self):
        """初始化配置"""
        self.config_store = SocialConfigStore(self.config_path)
        config = self.config_store.load_runtime()
        os.makedirs(self.sessions_dir, exist_ok=True)
        self._interrupt_merge_window_seconds = self._get_merge_window_seconds(config)

        # 初始化 router 和 engine
        dedup_path = os.path.join(self.sessions_dir, "dedup.json")
        dedup_store = FileDedupStore(dedup_path)
        self._router = MessageRouter(config, dedup_store)
        self._engine = SocialEngine()

    def _get_merge_window_seconds(self, config: Dict) -> float:
        """读取打断合并窗口秒数"""
        global_config = config.get("global") or {}
        try:
            return float(global_config.get("interrupt_merge_window_seconds", 0.8) or 0.8)
        except (TypeError, ValueError):
            return 0.8

    async def _start_adapter(self, account_config: Dict):
        """启动适配器"""
        platform = account_config.get("platform")
        adapter = self._create_adapter(platform)
        if adapter:
            account_id = account_config.get("id")
            await adapter.start(account_config, self._on_message)
            self._adapters[account_id] = adapter
            log(f"Adapter {account_id} started")

    def _on_message(self, message: UnifiedMessage):
        """消息回调 - route 后进入会话打断/重组状态机"""
        result = self._router.route(message)
        if not result.allowed:
            log(f"Route rejected: {result.reason}")
            return
        self._receive_session_message(message, result.account)

    def _receive_session_message(self, message: UnifiedMessage, account_config: Dict):
        """接收同会话消息, 如有活跃回复则打断并重组"""
        key = message.session_key
        with self._session_lock:
            state = self._session_states.setdefault(key, {
                "active": False,
                "cancel_event": None,
                "active_messages": [],
                "pending_messages": [],
                "pending_includes_active": False,
                "timer": None,
                "ready": False,
                "account": account_config,
            })
            state["account"] = account_config

            if state["active"]:
                cancel_event = state.get("cancel_event")
                if cancel_event:
                    cancel_event.set() # noqa
                if not state["pending_includes_active"]:
                    state["pending_messages"] = list(state["active_messages"]) + state["pending_messages"]
                    state["pending_includes_active"] = True

            state["pending_messages"].append(message)
            self._reset_session_timer_locked(key, state)

    def _reset_session_timer_locked(self, key: str, state: Dict):
        """重置同会话短合并窗口计时器"""
        timer = state.get("timer")
        if timer:
            timer.cancel()
        timer = threading.Timer(self._interrupt_merge_window_seconds, self._flush_session_pending, args=(key,))
        timer.daemon = True
        state["timer"] = timer
        timer.start()

    def _flush_session_pending(self, key: str):
        """合并窗口到期后启动或标记下一次回复"""
        with self._session_lock:
            state = self._session_states.get(key)
            if not state:
                return
            state["timer"] = None
            if state["active"]:
                state["ready"] = True
                return
            self._start_session_job_locked(key, state)

    def _start_session_job_locked(self, key: str, state: Dict):
        """启动同会话回复任务, 调用方需持有 _session_lock"""
        if not state["pending_messages"]:
            state["ready"] = False
            return

        messages = state["pending_messages"]
        state["pending_messages"] = []
        state["pending_includes_active"] = False
        state["ready"] = False
        cancel_event = threading.Event()

        state["active"] = True
        state["cancel_event"] = cancel_event
        state["active_messages"] = list(messages)
        account_config = state["account"]

        self._submit_session_job(key, messages, account_config, cancel_event)

    def _submit_session_job(self, key: str, messages, account_config: Dict, cancel_event: threading.Event):
        """线程安全提交阻塞式 engine 任务到 executor"""
        if not self._loop:
            log("No event loop for session job")
            return

        def submit():
            self._loop.run_in_executor(None, self._run_session_job, key, messages, account_config, cancel_event)

        if self._is_loop_thread():
            submit()
        else:
            self._loop.call_soon_threadsafe(submit)

    def _run_session_job(self, key: str, messages, account_config: Dict, cancel_event: threading.Event):
        """在线程中执行同会话模型回复"""
        typing_stop_event = threading.Event()
        typing_thread = None
        try:
            merged_message = self._build_merged_message(messages)
            typing_thread = self._start_typing_keepalive(
                merged_message,
                account_config,
                cancel_event,
                typing_stop_event,
            )
            self._engine.reply(
                merged_message,
                on_stage=lambda stage, content: self._send_reply_if_current(
                    merged_message,
                    content,
                    account_config,
                    cancel_event,
                ),
                cancel_event=cancel_event,
                account_config=account_config,
            )
        except Exception as e:
            log(f"Engine error: {e}\n{traceback.format_exc()}")
        finally:
            typing_stop_event.set()
            if typing_thread:
                typing_thread.join(timeout=1)
            self._finish_session_job(key, cancel_event)

    def _send_reply_if_current(self, message: UnifiedMessage, content: str, account_config: Dict, cancel_event):
        """未取消时发送当前回复阶段"""
        if cancel_event and cancel_event.is_set():
            return
        self._send_reply(message, content, account_config)

    def _start_typing_keepalive(
        self,
        message: UnifiedMessage,
        account_config: Dict,
        cancel_event: threading.Event,
        stop_event: threading.Event,
    ):
        """启动平台原生 typing keepalive"""
        adapter = self._adapters.get(message.account_id)
        if not adapter or not hasattr(adapter, "send_typing"):
            return None
        if not self._loop or self._is_loop_thread():
            return None

        thread = threading.Thread(
            target=self._typing_keepalive_loop,
            args=(adapter, message, account_config, cancel_event, stop_event),
            daemon=True,
        )
        thread.start()
        return thread

    def _typing_keepalive_loop(
        self,
        adapter,
        message: UnifiedMessage,
        account_config: Dict,
        cancel_event: threading.Event,
        stop_event: threading.Event,
    ):
        """周期性发送 typing, 直到回复结束或被取消"""
        interval = getattr(self, "_typing_keepalive_interval_seconds", 4.0)

        while not stop_event.is_set():
            if cancel_event and cancel_event.is_set():
                break

            future = None
            try:
                future = asyncio.run_coroutine_threadsafe(
                    adapter.send_typing(account_config, message.conversation_id),
                    self._loop,
                )
                future.result(timeout=10)
            except TimeoutError:
                if future:
                    future.cancel()
                log("Typing send timeout")
            except Exception as e:
                log(f"Typing send failed: {e}")

            stop_event.wait(interval)

    def _finish_session_job(self, key: str, cancel_event: threading.Event):
        """结束同会话回复任务, 如已有重组消息则启动下一轮"""
        with self._session_lock:
            state = self._session_states.get(key)
            if not state or state.get("cancel_event") is not cancel_event:
                return
            state["active"] = False
            state["cancel_event"] = None
            state["active_messages"] = []

            if state["ready"] and state["pending_messages"]:
                self._start_session_job_locked(key, state)
            elif state["pending_messages"] and not state.get("timer"):
                self._reset_session_timer_locked(key, state)

    def _build_merged_message(self, messages):
        """将短时间连续消息合并为单次模型输入"""
        if len(messages) == 1:
            return messages[0]

        last = messages[-1]
        content = "The user sent %d consecutive messages. Treat them as one complete request and answer them together:\n%s" % (
            len(messages),
            "\n".join(f"{idx}. {msg.content}" for idx, msg in enumerate(messages, 1))
        )
        return UnifiedMessage(
            message_id=last.message_id,
            platform=last.platform,
            account_id=last.account_id,
            conversation_id=last.conversation_id,
            sender_id=last.sender_id,
            sender_name=last.sender_name,
            content=content,
            content_type=last.content_type,
            timestamp=last.timestamp,
            reply_to=last.reply_to,
            raw=last.raw,
        )

    def _get_send_lock(self, message: UnifiedMessage):
        """按平台账号和会话串行化平台发送"""
        key = (message.platform, message.account_id, message.conversation_id)
        with self._send_locks_lock:
            lock = self._send_locks.get(key)
            if not lock:
                lock = threading.Lock()
                self._send_locks[key] = lock
            return lock

    def _send_reply(self, message: UnifiedMessage, content: str, account_config: Dict = None):
        """发送回复消息, 等待发送完成以保证阶段顺序"""
        if not content:
            return

        adapter = self._adapters.get(message.account_id)
        if not adapter:
            log(f"No adapter for {message.account_id}")
            return

        if self._is_loop_thread():
            log("Send skipped: _send_reply called from event loop thread")
            return

        max_len = 3500
        chunks = [content[i:i + max_len] for i in range(0, len(content), max_len)]

        async def send():
            for chunk in chunks:
                try:
                    await adapter.send_message(
                        account_config or {"id": message.account_id, "platform": message.platform},
                        message.conversation_id,
                        chunk
                    )
                except Exception as e:
                    log(f"Send error: {e}")

        with self._get_send_lock(message):
            future = asyncio.run_coroutine_threadsafe(send(), self._loop)
            try:
                future.result(timeout=60)
            except TimeoutError:
                future.cancel()
                log("Send timeout")
            except Exception as e:
                log(f"Send failed: {e}")

    def _is_loop_thread(self) -> bool:
        """当前线程是否为 runner 事件循环线程"""
        return self._loop_thread_id is not None and threading.get_ident() == self._loop_thread_id

    def _on_shutdown(self, signum, frame):
        """关闭"""
        log("Shutting down...")
        self._running = False
        for adapter in self._adapters.values():
            try:
                self._loop.run_until_complete(adapter.stop())
            except Exception:
                pass
        self._loop.stop()

    def _create_adapter(self, platform: str):
        """创建适配器"""
        try:
            if platform == "telegram":
                from mod.project.agent.social.adapters.telegram import TelegramAdapter
                return TelegramAdapter()
            if platform == "discord":
                from mod.project.agent.social.adapters.discord import DiscordAdapter
                return DiscordAdapter()
            log(f"Unknown platform: {platform}")
            return None
        except Exception as e:
            log(f"Create adapter error: {e}")
            return None


def main():
    parser = argparse.ArgumentParser(description="Social Service Runner")
    parser.add_argument("--config", required=True)
    parser.add_argument("--sessions", required=True)
    args = parser.parse_args()

    runner = SocialRunner(args.config, args.sessions)
    runner.run()


if __name__ == "__main__":
    main()
