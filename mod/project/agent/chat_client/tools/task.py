from typing import Optional, List
import uuid
import os
import sys
from . import register_tool
from .base import _xml_response

if not "class/" in sys.path:
    sys.path.insert(0, "class/")
try:
    from public.hook_import import hook_import

    hook_import()
except:
    pass



# 子代理强制排除工具: 持久化/跨会话写入归主代理 orchestrator(对称无 RunCommand/Delete File), 不下沉 worker
_SUBAGENT_EXCLUDED_TOOLS = {"NoteSave", "DocSave"}


@register_tool(category="Agent", name_cn="Task Sub-agent", risk_level="low")
def Task(description: str, prompt: str, task_id: Optional[str] = None, system_prompt: Optional[str] = None,
         tools: Optional[List[str]] = None, **kwargs) -> str:
    """
    (read-only dispatch) Launch a read-only sub-agent to execute one assigned task with an isolated context.

    The sub-agent has ONLY read-only tools (panel tools + ReadOnlyCommand) — it cannot write, restart, or run arbitrary commands. It keeps heavy exploration out of your main context and returns only a summary. Recursion blocked.

    When to dispatch:
    - Open-ended exploration where each result determines the next step (shell diagnostics, multi-tool probing, wide log/config/file reading). Default to dispatching for exploration.
    - Self-contained read-only investigation you want to delegate.

    When NOT to dispatch:
    - Targeted confirmation — checks where you already know what you're verifying (status, log grep, config); faster inline than a sub-agent round-trip.
    - Planning / confirmation / write steps — that is your job (orchestrator)

    Args:
        description: Short task title.
        prompt: Detailed instructions for the sub-agent. Be specific about scope and what to return.
        task_id: Optional session ID to resume a previous sub-agent conversation.
        system_prompt: Optional custom system prompt (overrides default worker profile).
        tools: Optional custom tool list (overrides default).

    Returns: task_id + sub-agent output in <task_result> block.
    """

    # Deferred import to avoid circular dependency
    from mod.project.agent.chat_client.agent import Agent

    # 禁止递归: 子代理不允许再派生子代理 (入口守卫)
    if kwargs.get("parent_config", {}).get("is_subagent"):
        return _xml_response(
            "Task",
            "error",
            "Recursion blocked: sub-agents cannot spawn further sub-agents. "
            "Complete the task with your own tools, or return the unresolved part to the parent agent."
        )

    # system_prompt / tools 必须由 agent.py 注入 (通用 worker profile) 或主代理显式传入
    if not system_prompt or not tools:
        return _xml_response(
            "Task",
            "error",
            "Missing system_prompt or tools: the sub-agent profile must be injected by the agent runtime, "
            "or provided explicitly. Generic dispatch requires both."
        )

    # Session Management
    session_id = task_id if task_id else str(uuid.uuid4())

    # Configure Agent
    cwd = os.getcwd()
    parent_config = kwargs.get("parent_config", {})
    parent_session_id = kwargs.get("parent_session_id")

    config = {
        "model_name": "gpt-4o",  # Default
        "cwd": cwd,
        "max_tool_iterations": 50
    }

    # 继承父配置 (跳过 tools/system_prompt, 由子代理自己的 profile 决定)
    if parent_config:
        for k, v in parent_config.items():
            if k not in ["tools", "system_prompt", "max_tool_iterations"]:
                config[k] = v
        if parent_session_id:
            parent_sessions_dir = parent_config.get("sessions_dir", "sessions")
            # 子代理 session 嵌套在父 session 下: sessions/<parent_id>/<sub_id>
            config["sessions_dir"] = os.path.join(parent_sessions_dir, parent_session_id)

    # 强制移除子代理不应持有的工具(持久化/跨会话操作归主代理)
    tools = [t for t in (tools or []) if t not in _SUBAGENT_EXCLUDED_TOOLS]
    config["tools"] = tools
    config["system_prompt"] = system_prompt

    # 标记为子代理: parent_config 继承此标记, Task 入口守卫据此阻止二次派生
    config["is_subagent"] = True

    agent = Agent(session_id=session_id, config=config)

    try:
        full_response = ""
        full_prompt = f"Task: {description}\n\nInstructions:\n{prompt}"

        generator = agent.chat(full_prompt)

        for chunk in generator:
            if chunk.get("type") == "content":
                full_response += chunk.get("response", "")
            elif chunk.get("type") == "error":
                return _xml_response("Task", "error", f"Agent error: {chunk.get('data')}")

        output = [
            f"task_id: {session_id}",
            "",
            "<task_result>",
            full_response,
            "</task_result>"
        ]

        return _xml_response("Task", "done", "\n".join(output))

    except Exception as e:
        return _xml_response("Task", "error", f"Task execution failed: {str(e)}")
    finally:
        if hasattr(agent, "close"):
            agent.close()
