# coding: utf-8
"""MySQL operation tools - 6 tools registered to ToolRegistry.

Built on the mysql_engine abstraction; provides agent-callable MySQL
connect/query/write capabilities.
- Read-only (low risk, auto-join SAFE_READONLY_TOOLS):
    MysqlTestConnection / MysqlListDatabases / MysqlDescribeTable / MysqlQuery
- Write ops (high risk, need enable + confirm):
    MysqlExecute (DML) / MysqlExecuteDdl (DDL)
"""

import json
import os
import sys

from . import register_tool
from .base import _xml_response
from . import mysql_engine

# aaPanel runtime environment (mirrors panel_tools.py)
_panel_path = '/www/server/panel'
os.chdir(_panel_path)
sys.path.insert(0, _panel_path + "/class/")
sys.path.insert(0, _panel_path + "/class_v2/")

import public

try:
    from public.hook_import import hook_import
    hook_import()
except Exception:
    pass

from public import lang


# ============================================================================
# Internal helpers
# ============================================================================

def _done(tool, payload):
    """Success response: payload serialized as JSON."""
    return _xml_response(tool, "done", json.dumps(payload, ensure_ascii=False))


def _err(tool, msg):
    """Error response."""
    return _xml_response(tool, "error", str(msg))


def _describe_target(db_name="", sid=0):
    """Connection target description (no credentials)."""
    if sid:
        return "remote-server:sid=%s" % sid
    if db_name:
        return "db:%s" % db_name
    return "local-root"


def _audit(tool, db_name, sid, sql_preview, affected):
    """Write-op audit log (failure does not affect the main flow)."""
    try:
        target = "%s sid=%s" % (db_name, sid) if sid else db_name
        msg = "agent %s on %s, affected=%s, sql=%s" % (tool, target, affected, sql_preview)
        public.write_log_gettext("Database manager", "{}", (msg,))
    except Exception:
        pass


# ============================================================================
# Read-only tools (low risk -> auto-join SAFE_READONLY_TOOLS)
# ============================================================================

@register_tool(category="Database", name_cn="MysqlTestConnection", risk_level="low")
def MysqlTestConnection(db_name: str = "", sid: int = 0) -> str:
    """
    Test MySQL connectivity by running a server-side 'SELECT 1'. Use this FIRST to confirm the target is reachable before any real query.

    Returns: JSON {connected, target, version}.

    Args:
        db_name: panel-managed database name. Empty = instance-level via local root.
        sid: panel-managed remote server id. 0 = ignore.
    """
    try:
        conn = mysql_engine.get_connection(db_name, sid)
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1 AS ok, VERSION() AS version")
            row = cur.fetchone() or {}
            cur.close()
            return _done("MysqlTestConnection", {
                "connected": True,
                "target": _describe_target(db_name, sid),
                "version": row.get("version"),
            })
        finally:
            mysql_engine.close_connection(conn)
    except Exception as e:
        return _err("MysqlTestConnection", mysql_engine.map_mysql_error(e))


@register_tool(category="Database", name_cn="MysqlListDatabases", risk_level="low")
def MysqlListDatabases(sid: int = 0, with_tables: bool = False, limit: int = 200) -> str:
    """
    List user databases (system DBs hidden by default). Read-only, hardcoded information_schema queries only.

    Returns: JSON {databases:[{name, charset}], table_counts?:{db: count}}.
        When the database count exceeds `limit`, only the first `limit` are returned and
        `_truncated`/`total`/`limit` are set; raise `limit` if you need more.

    Workflow: MysqlListDatabases -> MysqlDescribeTable / MysqlQuery.

    Args:
        sid: panel-managed remote server id. 0 = local instance.
        with_tables: if True, also return per-database table counts.
        limit: Max databases to return (default 200). Beyond this a _truncated marker is added.
    """
    try:
        conn = mysql_engine.get_connection("", sid)
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT SCHEMA_NAME AS name, DEFAULT_CHARACTER_SET_NAME AS charset "
                "FROM information_schema.SCHEMATA "
                "WHERE SCHEMA_NAME NOT IN ('information_schema','performance_schema','sys') "
                "ORDER BY SCHEMA_NAME")
            dbs = cur.fetchall()
            result = {"databases": [{"name": r["name"], "charset": r.get("charset")} for r in dbs]}
            total = len(result["databases"])
            if total > limit:
                result["databases"] = result["databases"][:limit]
                result["_truncated"] = True
                result["total"] = total
                result["limit"] = limit
                result["_note"] = "%d more databases omitted; raise limit to see them" % (total - limit)
            if with_tables:
                cur.execute(
                    "SELECT TABLE_SCHEMA AS db, COUNT(*) AS cnt "
                    "FROM information_schema.TABLES "
                    "WHERE TABLE_SCHEMA NOT IN ('information_schema','performance_schema','sys') "
                    "GROUP BY TABLE_SCHEMA")
                result["table_counts"] = {r["db"]: int(r["cnt"]) for r in cur.fetchall()}
            cur.close()
            return _done("MysqlListDatabases", result)
        finally:
            mysql_engine.close_connection(conn)
    except Exception as e:
        return _err("MysqlListDatabases", mysql_engine.map_mysql_error(e))


@register_tool(category="Database", name_cn="MysqlDescribeTable", risk_level="low")
def MysqlDescribeTable(db_name: str, table: str, sid: int = 0) -> str:
    """
    Show columns and indexes of one table (information_schema, parameterized). Read-only.

    Returns: JSON {database, table, columns:[{field, type, nullable, key, default, extra, comment}], indexes:[{name, cols, non_unique}]}.

    Workflow: MysqlListDatabases(with_tables=True) -> MysqlDescribeTable -> MysqlQuery.

    Args:
        db_name: database name. Required.
        table: table name. Required.
        sid: panel-managed remote server id. 0 = local.
    """
    if not db_name or not table:
        return _err("MysqlDescribeTable", "Both db_name and table are required")
    if not mysql_engine.is_valid_identifier(db_name) or not mysql_engine.is_valid_identifier(table):
        return _err("MysqlDescribeTable", "db_name/table contains illegal characters (only letters/digits/underscore allowed)")
    try:
        conn = mysql_engine.get_connection(db_name, sid)
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT COLUMN_NAME AS field, COLUMN_TYPE AS type, IS_NULLABLE AS nullable, "
                "COLUMN_KEY AS `key`, COLUMN_DEFAULT AS `default`, EXTRA AS extra, COLUMN_COMMENT AS comment "
                "FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s ORDER BY ORDINAL_POSITION",
                (db_name, table))
            columns = cur.fetchall()
            cur.execute(
                "SELECT INDEX_NAME AS name, GROUP_CONCAT(COLUMN_NAME) AS cols, NON_UNIQUE AS non_unique "
                "FROM information_schema.STATISTICS "
                "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s GROUP BY INDEX_NAME, NON_UNIQUE",
                (db_name, table))
            indexes = cur.fetchall()
            cur.close()
            return _done("MysqlDescribeTable", {
                "database": db_name, "table": table,
                "columns": columns, "indexes": indexes})
        finally:
            mysql_engine.close_connection(conn)
    except Exception as e:
        return _err("MysqlDescribeTable", mysql_engine.map_mysql_error(e))


@register_tool(category="Database", name_cn="MysqlQuery", risk_level="low")
def MysqlQuery(sql: str, db_name: str = "", sid: int = 0, params: list = None, limit: int = 200) -> str:
    """
    Run a STRICTLY read-only SQL and return rows. Auto-enters the safe-readonly whitelist.

    Allowed prefixes ONLY: SELECT/SHOW/DESCRIBE/DESC/EXPLAIN/WITH/TABLE.
    Blocked anywhere: INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE/GRANT/RENAME/CREATE/..., and INTO OUTFILE/LOAD_FILE.
    No stacked queries (single statement). Comments stripped before validation.
    Parameters MUST be passed via `params` (%s placeholders) when used. Oversized results are truncated.

    Returns: JSON {columns, rows, rowcount, truncated}.

    Args:
        sql: a single read-only SQL statement. Required.
        db_name: panel-managed database name. Empty = instance-level via local root.
        sid: panel-managed remote server id. 0 = ignore.
        params: bind values for %s placeholders as list (required if sql contains %s). E.g. sql="SELECT * FROM t WHERE id=%s", params=[42].
        limit: max rows to fetch (default 200, hard cap 500).
    """
    ok, reason = mysql_engine.validate_readonly_sql(sql, params)
    if not ok:
        return _err("MysqlQuery", reason)
    try:
        conn = mysql_engine.get_connection(db_name, sid)
        try:
            payload = mysql_engine.execute_query(conn, sql, params, limit)
            return _done("MysqlQuery", payload)
        finally:
            mysql_engine.close_connection(conn)
    except Exception as e:
        return _err("MysqlQuery", mysql_engine.map_mysql_error(e))


# ============================================================================
# Write tools (high risk -> NOT in the safe whitelist; need enable + confirm)
# ============================================================================

@register_tool(category="Database", name_cn="MysqlExecute", risk_level="high")
def MysqlExecute(sql: str, db_name: str, sid: int = 0, params: list = None, confirm: bool = False) -> str:
    """
    Execute a single DML statement (INSERT/REPLACE/UPDATE/DELETE). HIGH RISK - never in safe-readonly whitelist.

    DDL (CREATE/ALTER/DROP/TRUNCATE/RENAME) is refused - use MysqlExecuteDdl. Single statement only.
    Parameterized execution enforced. Audited via panel operation log. Auto-commit per statement.

    Returns: JSON {affected_rows, sql_preview, executed}.

    Args:
        sql: single DML statement with %s placeholders. Required.
        db_name: target panel-managed database. Required - writes are never instance-wide.
        sid: panel-managed remote server id. 0 = local.
        params: bind values for %s (required if sql contains %s).
        confirm: False = dry-run preview only (no data touched); True = execute. MUST be True to apply changes.
    """
    if not db_name:
        return _err("MysqlExecute", "Write operations require db_name")
    category, reason = mysql_engine.classify_write_sql(sql)
    if category != "dml":
        return _err("MysqlExecute", reason or "Only INSERT/REPLACE/UPDATE/DELETE are allowed")
    if mysql_engine.is_system_db(db_name) or mysql_engine.targets_system_schema(sql):
        return _err("MysqlExecute", "Writes to system schemas are forbidden; use DBChangePassword for password changes")
    ph = mysql_engine.strip_comments(sql).count("%s")
    if ph > 0 and (not params or len(params) != ph):
        return _err("MysqlExecute", "SQL has %d %%s placeholder(s); params count mismatch" % ph)
    if not confirm:
        return _done("MysqlExecute", {
            "executed": False, "affected_rows": 0,
            "sql_preview": mysql_engine.sql_preview(sql),
            "note": "confirm=False: dry-run preview only; pass confirm=True to execute"})
    try:
        conn = mysql_engine.get_connection(db_name, sid)
        try:
            res = mysql_engine.execute_write(conn, sql, params)
            _audit("MysqlExecute", db_name, sid, res["sql_preview"], res["affected_rows"])
            res["executed"] = True
            return _done("MysqlExecute", res)
        finally:
            mysql_engine.close_connection(conn)
    except Exception as e:
        return _err("MysqlExecute", mysql_engine.map_mysql_error(e))


@register_tool(category="Database", name_cn="MysqlExecuteDdl", risk_level="high")
def MysqlExecuteDdl(sql: str, db_name: str, sid: int = 0, confirm: bool = False) -> str:
    """
    Execute a single DDL statement (CREATE/ALTER/DROP/TRUNCATE/RENAME). HIGHEST RISK.

    System databases (mysql/information_schema/performance_schema/sys) are PROTECTED - DDL targeting them is always refused, even with confirm=True.
    Single statement only. No params (DDL does not use placeholders).

    Returns: JSON {affected_rows, sql_preview, executed}.

    Args:
        sql: single DDL statement. Required.
        db_name: target database. Required.
        sid: panel-managed remote server id. 0 = local.
        confirm: False = preview only; True = execute. MUST be True to apply.
    """
    if not db_name:
        return _err("MysqlExecuteDdl", "DDL requires db_name")
    if mysql_engine.is_system_db(db_name):
        return _err("MysqlExecuteDdl", "DDL on system database (%s) is forbidden" % db_name)
    category, reason = mysql_engine.classify_write_sql(sql)
    if category != "ddl":
        return _err("MysqlExecuteDdl", reason or "Only CREATE/ALTER/DROP/TRUNCATE/RENAME are allowed")
    if not confirm:
        return _done("MysqlExecuteDdl", {
            "executed": False, "affected_rows": 0,
            "sql_preview": mysql_engine.sql_preview(sql),
            "note": "confirm=False: dry-run preview only; pass confirm=True to execute"})
    try:
        conn = mysql_engine.get_connection(db_name, sid)
        try:
            res = mysql_engine.execute_write(conn, sql)
            _audit("MysqlExecuteDdl", db_name, sid, res["sql_preview"], res["affected_rows"])
            res["executed"] = True
            return _done("MysqlExecuteDdl", res)
        finally:
            mysql_engine.close_connection(conn)
    except Exception as e:
        return _err("MysqlExecuteDdl", mysql_engine.map_mysql_error(e))
