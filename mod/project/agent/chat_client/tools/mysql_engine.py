# coding: utf-8
"""MySQL abstraction engine.

Responsibilities:
- Connection acquisition: reuse panel credentials (table lookup + /etc/my.cnf parsing),
  return a pymysql connection (DictCursor + parameterized + explicit commit).
- SQL safety validation: layered defense pipeline (comment stripping, stacked-query
  detection, prefix whitelist, write-keyword blacklist, sensitive-column guard,
  parameterization enforcement).
- Execution & result mapping: read-only query / write op, unified normalized output.
- Error code mapping.

Design: only the standard library is imported at module top-level; public/pymysql
are imported lazily inside functions, so pure-logic functions (strip_comments,
validate_readonly_sql, ...) stay unit-testable without a panel environment.

Out of scope: business logic, connection pooling, full SQL AST parsing.
"""

import re
import datetime
from decimal import Decimal

# ============================================================================
# Resource constants (conservative safety values; oversized results/SQL are
# truncated or rejected to bound agent tool output).
# ============================================================================
MAX_ROWS = 500               # hard cap on fetched rows (larger result sets are truncated)
DEFAULT_ROWS = 200           # default row limit for read queries
MAX_SQL_LEN = 2000           # max SQL length (longer statements are rejected)
READONLY_TIMEOUT_MS = 10000  # statement-level timeout for read-only SELECT (MAX_EXECUTION_TIME, MySQL 5.7.4+)
SYSTEM_DBS = {"mysql", "information_schema", "performance_schema", "sys"}

# ============================================================================
# SQL validation constants
# ============================================================================
# Allowed statement prefixes for read-only queries
READONLY_PREFIXES = {"SELECT", "SHOW", "DESCRIBE", "DESC", "EXPLAIN", "WITH", "TABLE"}
# Write-statement prefixes
DML_PREFIXES = {"INSERT", "REPLACE", "UPDATE", "DELETE"}
DDL_PREFIXES = {"CREATE", "ALTER", "DROP", "TRUNCATE", "RENAME"}
# DDL object-type words (second keyword) used by _ddl_target to scope direct-tool DDL.
# Only table/index/view DDL is permitted; database/user DDL bypasses panel records.
_DDL_DB_WORDS = {"DATABASE", "SCHEMA"}   # database-level -> reject (use DBCreate/DBDelete)
_DDL_TABLE_WORDS = {"TABLE"}             # table-level -> allow (does not affect panel records)
_DDL_TABLE_AUX = {"INDEX", "VIEW"}       # table-auxiliary -> allow

# Write/admin keywords forbidden in a read-only context (word-boundary match, so
# identifiers like updated_at/payload are NOT falsely matched). Also defends against
# WITH...UPDATE writable CTEs and SELECT...INTO OUTFILE/LOAD_FILE style hazards.
_READONLY_DANGER_RE = re.compile(
    r"\b(?:INSERT|REPLACE|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|"
    r"RENAME|LOAD|CALL|LOCK|UNLOCK|FLUSH|RESET|KILL|SHUTDOWN|HANDLER|DO)\b"
    r"|INTO\s+OUTFILE|INTO\s+DUMPFILE|LOAD_FILE\s*\(",
    re.IGNORECASE,
)

# MySQL errno (int) / SQLSTATE (str) -> friendly English message.
# code may be an int errno (pymysql args[0]) or a str SQLSTATE.
MYSQL_ERROR_MAP = {
    # Access / privilege
    1040: "Too many connections",
    1042: "Unable to connect to any configured MySQL host",
    1044: "Access denied - insufficient privileges or database does not exist",
    1045: "Access denied - invalid username or password",
    1095: "You are not the owner of the target thread",
    1142: "Command denied - insufficient privileges for this operation",
    1149: "You have an error in your SQL syntax",
    1227: "Access denied - SUPER privilege required",
    1396: "Operation failed - target already exists or does not exist",
    # Database / table / column existence
    1049: "Unknown database",
    1051: "Unknown table",
    1054: "Unknown column",
    1146: "Table does not exist",
    1176: "Failed to open the referenced table / key does not exist",
    1347: "The target is not a BASE TABLE",
    1356: "View references invalid table(s) or column(s)",
    # Data integrity
    1062: "Duplicate entry - the record already exists",
    1169: "Unique constraint violation - duplicate row",
    1216: "Cannot add/update a child row - a foreign key constraint fails",
    1217: "Cannot delete/update a parent row - a foreign key constraint fails (child record exists)",
    1451: "Cannot delete/update a row - a foreign key constraint fails (parent record referenced)",
    1452: "Cannot add/update a child row - a foreign key constraint fails (parent row missing)",
    # Syntax / runtime
    1064: "You have an error in your SQL syntax",
    1205: "Lock wait timeout exceeded; try restarting the transaction",
    1213: "Deadlock found when trying to get lock; retry the transaction",
    1317: "Query execution was interrupted",
    # Connection / protocol (CR_*)
    2002: "Connection failed - cannot connect to local MySQL socket (check MySQL service status)",
    2003: "Cannot connect to MySQL server (check host/port and network)",
    2005: "Unknown MySQL server host",
    2006: "MySQL server has gone away",
    2013: "Lost connection to MySQL server during query",
    2026: "SSL connection error",
    # SQLSTATE
    "21000": "Cardinality violation",
    "22000": "Data exception",
    "23000": "Integrity constraint violation",
    "42000": "Syntax error or access rule violation",
    "HY000": "General database error",
}

# Valid bare identifier (db/table name), guards information_schema query inputs
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# ============================================================================
# Pure-logic functions (no external deps; unit-testable on Windows)
# ============================================================================

def strip_comments(sql):
    """Strip SQL comments: block (incl. MySQL conditional /*!...*/), # line, -- line.
    Must run before every structural check to prevent comment-based bypass
    (e.g. /*!50000 DROP TABLE x*/)."""
    if not sql:
        return ""
    s = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)  # block (incl. conditional)
    s = re.sub(r"#[^\n]*", " ", s)                        # # line comment
    s = re.sub(r"--[ \t][^\n]*", " ", s)                  # -- line comment (needs trailing space/tab)
    return s


def _strip_strings(sql):
    """Replace string literals with empty quotes so literal text cannot disturb structural checks."""
    s = re.sub(r"'(?:[^'\\]|\\.)*'", "''", sql)
    s = re.sub(r'"(?:[^"\\]|\\.)*"', '""', s)
    return s


def _normalize(sql):
    """Strip comments + string literals and return pure structural text."""
    return _strip_strings(strip_comments(sql))


def has_stacked_queries(sql):
    """Detect stacked queries: after stripping strings, any ';' beyond a single trailing one."""
    s = _strip_strings(sql).strip()
    if s.endswith(";"):
        s = s[:-1].rstrip()
    return ";" in s


def _first_word(sql):
    """Return the first keyword of normalized text (leading parens/whitespace trimmed)."""
    s = sql.strip().lstrip("(").strip()
    if not s:
        return ""
    return s.split(None, 1)[0].upper()


def is_system_db(db_name):
    """Return True if the name is a MySQL system database."""
    if not db_name:
        return False
    return db_name.strip().strip("`").lower() in SYSTEM_DBS


def is_valid_identifier(name):
    """Return True if name is a valid bare SQL identifier (guards information_schema inputs)."""
    return bool(name) and bool(_IDENT_RE.match(name))


def _scan_block_comments(sql):
    """Scan block-comment bodies; return the first write/admin keyword found.
    Defends against MySQL conditional comments /*!...*/ which ARE executed.
    Plain /* */ is ignored by MySQL, but we still scan it to be safe."""
    for c in re.findall(r"/\*.*?\*/", sql, flags=re.DOTALL):
        m = _READONLY_DANGER_RE.search(c)
        if m:
            return m.group(0).strip()
    return None


def validate_readonly_sql(sql, params=None):
    """Multi-layer read-only SQL validation; returns (ok, reason).
    Layer0 size/empty/control-char -> Layer1 strip comments + scan block comments ->
    Layer2 stacked queries -> Layer3 prefix whitelist -> Layer4 write-keyword blacklist ->
    Layer5 sensitive columns -> Layer6 parameterization enforcement."""
    if not sql or not sql.strip():
        return False, "SQL is empty"
    if len(sql) > MAX_SQL_LEN:
        return False, "SQL too long (exceeds %d chars)" % MAX_SQL_LEN
    if "\x00" in sql:
        return False, "SQL contains illegal control characters"

    stripped = strip_comments(sql)
    bad_kw = _scan_block_comments(sql)
    if bad_kw:
        return False, "Write/admin keyword found inside a comment (possible conditional-comment injection): %s" % bad_kw
    if has_stacked_queries(stripped):
        return False, "Stacked queries are not allowed"

    first = _first_word(stripped)
    if first not in READONLY_PREFIXES:
        return False, "Only read-only statements allowed (%s); got prefix: %s" % (", ".join(sorted(READONLY_PREFIXES)), first)

    norm = _normalize(sql)
    m = _READONLY_DANGER_RE.search(norm)
    if m:
        return False, "Write/admin keyword forbidden in read-only query: %s" % m.group(0).strip()

    # Sensitive-column guard (e.g. SELECT password FROM mysql.user)
    if re.search(r"\b(?:password|authentication_string)\b", norm, re.IGNORECASE) or \
       re.search(r"\bmysql\.(?:user|db)\b", norm, re.IGNORECASE):
        return False, "Querying system sensitive columns (password/authentication_string/mysql.user) is forbidden"

    # Parameterization enforcement
    placeholder_count = stripped.count("%s")
    if placeholder_count > 0:
        param_len = len(params) if isinstance(params, (list, tuple)) else 0
        if param_len != placeholder_count:
            return False, "SQL has %d %%s placeholder(s) but params count is %d" % (placeholder_count, param_len)

    return True, ""


def _ddl_target(stripped, first):
    """Parse the DDL object type from the second keyword.
    Returns one of: database / user / table / index / view / unknown."""
    words = stripped.split()
    second = words[1].upper() if len(words) > 1 else ""
    if first == "RENAME":
        if second == "TABLE":
            return "table"
        if second == "USER":
            return "user"
        return "unknown"
    if second in _DDL_DB_WORDS:
        return "database"
    if second == "USER":
        return "user"
    if second in _DDL_TABLE_WORDS:
        return "table"
    if second in _DDL_TABLE_AUX:
        return second.lower()
    return "unknown"


def targets_system_schema(sql):
    """Return True if SQL references a system-schema table (mysql./information_schema/...).
    Guards DML writes that bypass panel records (e.g. UPDATE mysql.user to change passwords)."""
    return re.search(r"\b(?:mysql|information_schema|performance_schema|sys)\s*\.",
                     _normalize(sql), re.IGNORECASE) is not None


def classify_write_sql(sql):
    """Classify a write SQL; returns (category, reason), category in {'dml','ddl',''}."""
    if not sql or not sql.strip():
        return "", "SQL is empty"
    if len(sql) > MAX_SQL_LEN:
        return "", "SQL too long (exceeds %d chars)" % MAX_SQL_LEN
    stripped = strip_comments(sql)
    bad_kw = _scan_block_comments(sql)
    if bad_kw:
        return "", "Write/admin keyword found inside a comment (possible conditional-comment injection): %s" % bad_kw
    if has_stacked_queries(stripped):
        return "", "Stacked queries are not allowed"
    first = _first_word(stripped)
    if first in DML_PREFIXES:
        return "dml", ""
    if first in DDL_PREFIXES:
        target = _ddl_target(stripped, first)
        if target in ("table", "index", "view"):
            return "ddl", ""
        if target == "database":
            return "", "Database-level DDL is forbidden in direct tools; use DBCreate/DBDelete to keep panel records in sync"
        if target == "user":
            return "", "User-management DDL is forbidden in direct tools; use DBChangePassword to keep panel records in sync"
        return "", "Only TABLE/INDEX/VIEW DDL is permitted in direct tools (got %s)" % target
    return "", "Not a write statement (prefix %s); use MysqlExecute for DML, MysqlExecuteDdl for DDL" % first


def map_mysql_error(exc):
    """Map a MySQL exception to a friendly English message.
    Handles int errno (pymysql) and str SQLSTATE; tolerates non-standard arg shapes."""
    try:
        code = exc.args[0]
    except (AttributeError, IndexError, TypeError):
        return str(exc)
    # direct lookup (int errno or str SQLSTATE)
    msg = MYSQL_ERROR_MAP.get(code)
    if msg:
        tag = "errno" if isinstance(code, int) else "sqlstate"
        return "%s (%s %s)" % (msg, tag, code)
    # numeric-string code -> int lookup (some drivers pass code as str)
    if isinstance(code, str) and code.isdigit():
        msg = MYSQL_ERROR_MAP.get(int(code))
        if msg:
            return "%s (errno %s)" % (msg, code)
    return str(exc)


def _jsonable(v):
    """Convert Decimal/datetime/bytes to a JSON-serializable value."""
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (datetime.datetime, datetime.date, datetime.time)):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray)):
        try:
            return v.decode("utf-8", "ignore")
        except Exception:
            return str(v)
    return v


def result_to_payload(rows, limit=DEFAULT_ROWS):
    """Normalize DictCursor rows (list of dict) into {columns, rows, rowcount, truncated}."""
    rows = rows or []
    truncated = len(rows) >= limit
    if not rows:
        return {"columns": [], "rows": [], "rowcount": 0, "truncated": truncated}
    columns = list(rows[0].keys())
    row_list = [[_jsonable(r.get(c)) for c in columns] for r in rows]
    return {"columns": columns, "rows": row_list, "rowcount": len(row_list), "truncated": truncated}


def sql_preview(sql, n=200):
    """Return a truncated SQL preview (placeholders NOT expanded, to avoid leaking bound values)."""
    sql = (sql or "").strip()
    return sql if len(sql) <= n else sql[:n] + "..."


# ============================================================================
# Connection & execution (depend on public/pymysql; lazily imported)
# ============================================================================

def _local_root_params(database=None):
    """Local root connection params: password from config table, port/socket from /etc/my.cnf."""
    import public
    password = public.M("config").where("id=?", (1,)).getField("mysql_root")
    socket_path = "/tmp/mysql.sock"
    port = 3306
    try:
        myconf = public.readFile("/etc/my.cnf")
        if myconf:
            m = re.search(r"socket\s*=\s*(.+)", myconf)
            if m:
                socket_path = m.group(1).strip()
            m = re.search(r"port\s*=\s*([0-9]+)", myconf)
            if m:
                port = int(m.group(1))
    except Exception:
        pass
    return {
        "host": "localhost", "port": port, "user": "root",
        "password": password, "database": database,
        "unix_socket": socket_path,
    }


def _resolve_conn_params(db_name="", sid=0):
    """Resolve connection params, priority: sid > db_name > local root.
    Reuses panel credentials (databases/database_servers tables); credentials are never returned."""
    import json
    import public

    sid = int(sid or 0)
    if sid:  # remote server
        srv = public.M("database_servers").where("id=?", (sid,)).find()
        if not srv:
            raise ValueError("Remote server does not exist (sid=%s)" % sid)
        return {
            "host": srv["db_host"], "port": int(srv["db_port"]),
            "user": srv["db_user"], "password": srv["db_password"],
            "database": db_name or None, "unix_socket": None,
        }
    if db_name:  # database specified
        db = public.M("databases").where("name=?", (db_name,)).find()
        if not db:
            raise ValueError("Database does not exist: %s" % db_name)
        if db.get("sid"):  # bound to a remote server
            srv = public.M("database_servers").where("id=?", (db.get("sid"),)).find()
            if not srv:
                raise ValueError("Bound remote server does not exist")
            return {
                "host": srv["db_host"], "port": int(srv["db_port"]),
                "user": srv["db_user"], "password": srv["db_password"],
                "database": db_name, "unix_socket": None,
            }
        if str(db.get("db_type")) == "1":  # standalone remote database
            try:
                cc = json.loads(db.get("conn_config") or "{}")
            except Exception:
                cc = {}
            return {
                "host": cc.get("db_host", "localhost"), "port": int(cc.get("db_port", 3306)),
                "user": cc.get("db_user", "root"), "password": cc.get("db_password", ""),
                "database": db_name, "unix_socket": None,
            }
        return _local_root_params(db_name)  # local database
    return _local_root_params(None)  # local root, instance-level


def get_connection(db_name="", sid=0):
    """Return a pymysql connection (DictCursor + parameterized + explicit commit).
    Local path uses unix_socket; falls back to TCP 127.0.0.1 on socket failure."""
    import pymysql
    params = _resolve_conn_params(db_name, sid)
    base = dict(
        host=params["host"], port=params["port"], user=params["user"],
        password=params["password"], charset="utf8mb4",
        connect_timeout=10, read_timeout=60, write_timeout=60,
        cursorclass=pymysql.cursors.DictCursor, # noqa
    )
    if params.get("database"):
        base["database"] = params["database"]
    try:
        if params.get("unix_socket"):
            return pymysql.connect(unix_socket=params["unix_socket"], **base)
        return pymysql.connect(**base)
    except Exception:
        if params.get("unix_socket"):  # local socket failed -> TCP fallback
            base["host"] = "127.0.0.1"
            return pymysql.connect(**base)
        raise


def close_connection(conn):
    """Safely close a connection."""
    try:
        if conn:
            conn.close()
    except Exception:
        pass


def execute_query(conn, sql, params=None, limit=DEFAULT_ROWS):
    """Run a read-only query and return a payload dict. Injects a SELECT statement timeout."""
    if limit > MAX_ROWS:
        limit = MAX_ROWS
    if limit < 1:
        limit = 1
    cur = conn.cursor()
    try:
        try:  # MySQL 5.7.4+ SELECT-only timeout; lower versions raise and we ignore
            cur.execute("SET SESSION MAX_EXECUTION_TIME=%s" % READONLY_TIMEOUT_MS)
        except Exception:
            pass
        if params:
            cur.execute(sql, params)
        else:
            cur.execute(sql)
        rows = cur.fetchmany(limit)
        return result_to_payload(rows, limit)
    finally:
        try:
            cur.close()
        except Exception:
            pass


def execute_write(conn, sql, params=None):
    """Run a write op; returns {affected_rows, sql_preview}. Commits explicitly."""
    cur = conn.cursor()
    try:
        if params:
            affected = cur.execute(sql, params)
        else:
            affected = cur.execute(sql)
        conn.commit()
        return {"affected_rows": int(affected or 0), "sql_preview": sql_preview(sql)}
    finally:
        try:
            cur.close()
        except Exception:
            pass
