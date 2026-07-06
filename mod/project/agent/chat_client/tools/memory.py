# coding: utf-8
# -------------------------------------------------------------------
# aapanel
# -------------------------------------------------------------------
# Copyright (c) 2015-2099 aapanel(http://www.aapanel.com) All rights reserved.
# -------------------------------------------------------------------
# Author: aapanel
# -------------------------------------------------------------------

"""记忆: NoteSave DocSave"""
import os
import re
import time

from typing import Dict

from . import register_tool
from .base import _is_blocked_path, _xml_response, atomic_update_json
from mod.project.agent.dynamic import MEMORIES_DIR

_TOPIC_RE = re.compile(r'^[a-z0-9_]+(?:[_-][a-z0-9]+)*$')  # snake_case, 可选 _/- 分隔
_VALID_TYPES = frozenset({"fact", "preference", "decision", "pitfall", "milestone"})

# 指针: [[topic]] / [[docs/name]], 合法格式(cleanup_pointers 用, 区分合法 vs 非法笔误)
_POINTER_RE = re.compile(r'\[\[(docs/)?([a-z0-9_]+(?:[_-][a-z0-9]+)*)\]\]')


@register_tool(category="Agent", name_cn="NoteSave", risk_level="low", internal=True)
def NoteSave(topic: str, type: str, content: str, **kwargs) -> str:
    """Persist a durable fact so it survives across sessions and informs future turns.

Call when the conversation yields durable value:
- Environment/architecture (fact): "main site runs nginx + php-fpm + mysql 8.0"
- Preferences/conventions (preference): "always back up DB before changes", "use a gentle tone"
- Decisions (decision): "standardize on mysql 8.0"
- Resolved pitfalls (pitfall): symptom + root cause + fix
- Milestones (milestone): "migrated to mysql 8.0"

Skip if the turn yielded only ephemeral or already-known information. Resource lifecycle aaPanel already tracks (creating/deleting sites, databases, SSL, firewall rules, cron, etc.) is panel state, not durable knowledge — record the non-obvious *why* behind it, not the event itself.

Args:
    topic: short theme label (snake_case, ≤128 chars), e.g. nginx, mysql, site_example_com,
        preferences. Group by subject, not by type — all nginx facts/pitfalls go under
        topic=nginx, not topic=pitfalls. One file per theme — do NOT encode events/dates/instances here (use content).
    type: one of fact / preference / decision / pitfall / milestone.
    content: single self-contained line, one fact per call (multiple facts → multiple
        calls), ≤500 chars (longer → DocSave). For pitfall use "symptom → root cause → fix".
        Duplicates auto-skip; do not paraphrase an existing note just to reword it. Reference
        another memory with [[<topic>]] or a doc with [[docs/<name>]] when its key fact lives
        there (avoid duplicating it); the doc itself is NOT in context — Read it separately
        if you need the details.
"""
    if not _TOPIC_RE.match(topic or ""):
        return _xml_response("NoteSave", "error", f"invalid topic: {topic}")
    if len(topic) > 128:
        return _xml_response("NoteSave", "error", "topic too long (max 128 chars)")
    if type not in _VALID_TYPES:
        return _xml_response("NoteSave", "error", f"invalid type: {type} (must be one of {sorted(_VALID_TYPES)})")
    if not content:
        return _xml_response("NoteSave", "error", "empty content")

    # 单行兜底: 压平所有空白(\n/\r/多空格)为单空格, 防破坏 md 列表结构
    content = ' '.join(content.split())
    if not content:
        return _xml_response("NoteSave", "error", "empty content after sanitize")
    if len(content) > 500:
        return _xml_response("NoteSave", "error", "content too long (max 500 chars) — use DocSave for long-form knowledge")

    os.makedirs(MEMORIES_DIR, exist_ok=True)
    path = os.path.join(MEMORIES_DIR, f"{topic}.md")

    try:
        with open(path, "r", encoding="utf-8") as f:
            existing = f.read()
    except FileNotFoundError:
        existing = ""

    # 去重: 全文匹配 content
    if content in existing:
        return _xml_response("NoteSave", "done", f"already_exists topic={topic}")

    line = f"- [{type} {time.strftime('%Y-%m-%d')}] {content}\n"
    if not existing:
        line = f"# {topic}\n\n{line}"
    elif not existing.endswith("\n"):
        line = "\n" + line

    with open(path, "a", encoding="utf-8") as f:
        f.write(line)

    return _xml_response("NoteSave", "done", f"saved topic={topic} type={type}")


@register_tool(category="Agent", name_cn="DocSave", risk_level="low", internal=True)
def DocSave(name: str, description: str, content: str, **kwargs) -> str:
    """Save a long-form knowledge document to memories/docs/<name>.md (create or overwrite).

    Use for document-level knowledge too large for a single memory line:
    - Complete troubleshooting playbooks, architecture decisions, standard procedures.

    Frontmatter (description + updated) is auto-managed. Reference this doc from memories via
    [[docs/<name>]]; inside content, link another doc with [[docs/<name>]] or a short memory
    with [[<topic>]].

    This overwrites the whole document. If a doc with this name may already exist, Read it first to avoid clobbering; then pass full content. Before creating a new doc, check the Available docs list in context — if a similar one exists, Read and overwrite it instead of creating a new name (prevents fragmentation).

    Args:
        name: filename (snake_case, ≤128), e.g. mysql_recovery.
        description: one-line summary (frontmatter; reserved for future sleep/cleanup and
            on-demand Read orientation, ≤120 chars).
        content: full Markdown body (multi-line, unlike NoteSave's one-line). Start the
            body with a `# title` heading; frontmatter is auto-prepended above it.
    """
    if not _TOPIC_RE.match(name or ""):
        return _xml_response("DocSave", "error", f"invalid name: {name}")
    if len(name) > 128:
        return _xml_response("DocSave", "error", "name too long (max 128 chars)")
    if not content or not content.strip():
        return _xml_response("DocSave", "error", "empty content")

    description = ' '.join((description or "").split())  # 单行兜底, 防 \n 破坏 frontmatter
    if not description:
        return _xml_response("DocSave", "error", "empty description")

    docs_dir = os.path.join(MEMORIES_DIR, "docs")
    os.makedirs(docs_dir, exist_ok=True)
    path = os.path.join(docs_dir, f"{name}.md")

    _frontmatter = (
        f"---\n"
        f"description: {description}\n"
        f"updated: {time.strftime('%Y-%m-%d')}\n"
        f"---\n\n"
    )
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(_frontmatter + content.strip() + "\n")
    except Exception as e:
        return _xml_response("DocSave", "error", f"write fail: {e}")

    return _xml_response("DocSave", "done", f"saved docs/{name}.md ({len(content)} chars)")


@register_tool(category="Agent", name_cn="Project Save", risk_level="low", internal=True)
def ProjectSave(project_id: str, files: Dict[str, str],
                meta_snapshot: Dict[str, str] = None,
                session_id: str = "", sessions_dir: str = "", **kwargs) -> str:
    """Persist project INFORMATION for a site-design project (memories/projects/<project_id>/).
    Third member of the memory-tool family alongside NoteSave (short facts) and DocSave (long docs) —
    manages the project's info docs + status/snapshot, NOT the generated artifact.

    **Scope: project information only** — the info docs (`meta.md` / `design.md` / `progress.md`) AND
    status/snapshot (`status` / `subject` / `style` via meta_snapshot). Batches info files in
    one call AND atomically syncs the chat-list snapshot.

    **Out of scope (use other tools)**:
    - `site/*` artifact (HTML/CSS/JS) → use `Write` (ProjectSave is not for the generated artifact).
    - `ui_spec.md` → fetched directly via `curl -o` (large, ~31KB, never relayed through the model).

    Never use `Write` / `RunCommand` (echo/cat/sed/tee) for the info docs or to mutate the session
    `meta.json` `project` block — those go through `ProjectSave`.

    When to use:
    - Project init: write meta.md + design.md + progress.md together; pass meta_snapshot to bind the session
    - Info update: write only changed info docs ({"design.md": ...})
    - Status transition: update meta.md and pass meta_snapshot={"status":...} to sync the chat list
    - Status-only snapshot update (no file change, e.g. just refresh status): pass files={} + meta_snapshot to sync the snapshot only

    Args:
        project_id: project slug (snake_case + short suffix), e.g. photo_studio_a3f7. Dir auto-created if absent.
        files: map of relative-path -> full content for INFO docs (meta/design/progress). May be empty {} when only updating meta_snapshot. NOT for site/* (use Write). Non-str values rejected.
        meta_snapshot: optional {status/subject/style} to sync into the session meta.json under project.{...}. Unknown keys ignored. Omit when only editing project files.
    """
    # project_id 复用 NoteSave 的 _TOPIC_RE(同属记忆族, 校验一致)
    if not _TOPIC_RE.match(project_id or ""):
        return _xml_response("ProjectSave", "error", f"invalid project_id: {project_id}")
    if not isinstance(files, dict):
        return _xml_response("ProjectSave", "error", "files must be a {path: content} map")
    if not files and not meta_snapshot:
        return _xml_response("ProjectSave", "error", "nothing to do: provide files and/or meta_snapshot")

    proj_real = os.path.realpath(os.path.join(MEMORIES_DIR, "projects", project_id))
    written, errors, ignored = [], [], []

    for rel, content in files.items():
        rel = (rel or "").replace("\\", "/").lstrip("/")
        # 显式拒绝空/./.. 防边界(撞项目根 / 穿越)
        if rel in ("", ".", "..") or rel.startswith("../") or "/.." in rel or rel.startswith("/"):
            errors.append(f"{rel}: rejected (invalid relative path)"); continue
        if not isinstance(content, str):
            errors.append(f"{rel}: content must be str, got {type(content).__name__}"); continue
        target = os.path.realpath(os.path.join(proj_real, rel))
        if not (target == proj_real or target.startswith(proj_real + os.sep)):
            errors.append(f"{rel}: rejected (escapes project dir)"); continue
        # _is_blocked_path 对 memories/projects/ 实际无效(黑名单不覆盖此目录), 保留作双保险
        is_blocked, reason = _is_blocked_path(target)
        if is_blocked:
            errors.append(f"{rel}: blocked ({reason})"); continue
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w", encoding="utf-8") as f:
                f.write(content)
            written.append(rel)
        except Exception as e:
            errors.append(f"{rel}: {e}")

    # files 全成功才同步 snapshot(防状态分裂: meta.md 文件 draft 而 snapshot generated)
    files_ok = not errors
    synced = ""
    if meta_snapshot and files_ok:
        if not (session_id and sessions_dir):
            errors.append("meta_snapshot given but session context missing — session meta NOT synced")
        else:
            allowed = ("status", "subject", "style")
            snap = {k: v for k, v in meta_snapshot.items() if k in allowed}
            bad = [k for k in meta_snapshot if k not in allowed]
            if bad:
                ignored.append(f"ignored meta_snapshot keys: {bad}")
            # sessions_dir为绝对路径
            meta_path = os.path.join(sessions_dir, session_id, "meta.json")

            def _m(d):
                # 跨会话保护: 当前会话已绑别的 project(existing_id 非空且≠project_id) →
                # 不篡改本会话绑定, 返回 None 取消写(atomic_update_json 见 None 不写 meta.json);
                # 仅新会话(existing_id 空) 或 本会话即该 project(==) 才绑定/刷新快照
                _existing = d.get("project") or {}
                _existing_id = _existing.get("id")
                if _existing_id and _existing_id != project_id:
                    _m.skip_bound = _existing_id
                    return None
                _m.skip_bound = None
                _existing["id"] = project_id
                _existing.update(snap)
                d["project"] = _existing
                d["chat_type"] = "website"
                return d
            _m.skip_bound = None

            try:
                ok2, msg2 = atomic_update_json(meta_path, _m)
                if ok2:
                    synced = (f"; session meta untouched (cross-session, bound to {_m.skip_bound})"
                              if _m.skip_bound
                              else f"; session synced ({','.join(snap) or 'id'})")
                else:
                    errors.append(f"session meta sync fail: {msg2}")
            except Exception as e:
                errors.append(f"session meta sync exception: {e}")

    # files 失败→error(不同步 snapshot, 防状态分裂); files 全成功→done(snapshot 失败仅 ERRORS 段, meta.md 已是真相); 无回滚, 模型须重试失败项
    parts = [f"wrote {len(written)}: {written}"]
    if synced:
        parts.append(synced)
    if ignored:
        parts.append("; ".join(ignored))
    if errors:
        parts.append(f"ERRORS: {errors}")
    return _xml_response("ProjectSave", "done" if (files_ok and (written or synced)) else "error", " | ".join(parts))


def cleanup_pointers(memories_dir=None) -> dict:
    """审计/清理指针: 清非法格式笔误 + 报告 unresolved(合法但目标不存在, 可能前向引用).

    不删合法指针(可能是前向引用, 允许 — [[x]] 指向未创建文件合法).
    仅清非法格式([[空]] / [[非法字符]]): 删 [[ ]] 保文字. 纯规则, 零 LLM.

    Returns:
        {invalid_cleaned, unresolved, unresolved_list, report}
    """
    from mod.project.agent.dynamic import MEMORIES_DIR as _DEFAULT
    _root = memories_dir or _DEFAULT
    _rep = {"invalid_cleaned": 0, "unresolved": 0, "unresolved_list": [], "report": ""}

    if not os.path.isdir(_root):
        _rep["report"] = "[CLEANUP] memories dir not found"
        return _rep

    # 目标存在集(合法指针的目标判定)
    _exist = {f[:-3] for f in os.listdir(_root) if f.endswith(".md")}
    _docs_dir = os.path.join(_root, "docs")
    if os.path.isdir(_docs_dir):
        _exist |= {"docs/" + f[:-3] for f in os.listdir(_docs_dir) if f.endswith(".md")}

    # 待扫描文件(顶层 + docs/)
    _files = [os.path.join(_root, f) for f in sorted(os.listdir(_root)) if f.endswith(".md")]
    if os.path.isdir(_docs_dir):
        _files += [os.path.join(_docs_dir, f) for f in sorted(os.listdir(_docs_dir)) if f.endswith(".md")]

    _any_re = re.compile(r'\[\[([^\]]*)\]\]')  # 所有 [[...]](含非法)
    for _path in _files:
        try:
            with open(_path, "r", encoding="utf-8") as _fh:
                _body = _fh.read()
        except Exception:
            continue
        _orig = _body

        # 1. 清非法格式指针(非 _POINTER_RE 的 [[...]]): 删 [[ ]] 保文字
        def _clean_illegal(m):
            if _POINTER_RE.fullmatch(m.group(0)):
                return m.group(0)  # 合法格式, 保留
            _rep["invalid_cleaned"] += 1
            return m.group(1)  # 非法: 删 [[ ]], 保文字
        _body = _any_re.sub(_clean_illegal, _body)

        # 2. 报告 unresolved(合法指针但目标不存在 — 可能前向引用, 不删)
        for _m in _POINTER_RE.finditer(_orig):
            _tgt = ("docs/" if _m.group(1) else "") + _m.group(2)
            if _tgt not in _exist:
                _rep["unresolved"] += 1
                _rep["unresolved_list"].append(f"{os.path.relpath(_path, _root)}: [[{_tgt}]]")

        if _body != _orig:
            try:
                with open(_path, "w", encoding="utf-8") as _fh:
                    _fh.write(_body)
            except Exception:
                pass

    _rep["report"] = "[CLEANUP] invalid_cleaned=%d unresolved=%d (forward-refs kept, not deleted)" % (
        _rep["invalid_cleaned"], _rep["unresolved"])
    return _rep
