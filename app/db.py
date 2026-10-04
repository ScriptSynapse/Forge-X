"""MySQL access layer for FORGE-X.

Design
------
* One connection pool per Flask app (mysql-connector-python pooling).
* One connection per request, borrowed lazily on first use and returned
  to the pool when the request ends (teardown_appcontext).
* autocommit=True: a single statement commits by itself. Multi-statement
  work uses ``with transaction() as cur:`` (explicit COMMIT/ROLLBACK), and
  the stored procedures manage their own transactions.
* Every helper takes SQL with %s placeholders and a params tuple. Values are
  never formatted into SQL strings, which is what prevents SQL injection.
* MySQL errors are translated into a few FORGE-X exceptions so routes can
  show friendly messages without leaking SQL details.
* Each connection gets @app_user_id and @app_ip session variables, which the
  role-change audit triggers read (decision D5), and the lab time zone (D1).
"""
import contextlib
import functools
import re
import threading

import mysql.connector
from mysql.connector import errorcode, pooling
from flask import current_app, g, has_request_context, request

_POOL_KEY = "forge_x_mysql_pool"
_pool_lock = threading.Lock()
_PROC_NAME = re.compile(r"^sp_[a-z0-9_]+$")

# MySQL error numbers we treat specially
ER_SIGNAL_EXCEPTION = 1644        # SIGNAL SQLSTATE '45000' from our procedures/triggers
ER_DUP_ENTRY = 1062
ER_ROW_IS_REFERENCED = 1451
ER_NO_REFERENCED_ROW = 1452
ER_CHECK_CONSTRAINT = 3819
ER_LOCK_DEADLOCK = 1213
ER_LOCK_WAIT_TIMEOUT = 1205
ER_TABLEACCESS_DENIED = 1142


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class DatabaseError(Exception):
    """Base class. `user_message` is always safe to show on a page.

    str(err) of an unclassified DatabaseError also includes MySQL's error
    number and text, so logs and test failures say what went wrong. Pages
    must therefore show `err.user_message`, never str(err), for these.
    """

    user_message = "A database error occurred. Please try again."

    def __init__(self, message=None, errno=None, detail=None):
        super().__init__(message or self.user_message)
        self.errno = errno
        self.detail = detail        # raw MySQL text: for logs only, never for users
        if message:
            self.user_message = message

    def __str__(self):
        base = super().__str__()
        if type(self) is DatabaseError and (self.errno or self.detail):
            return f"{base} [MySQL error {self.errno}: {self.detail}]"
        return base


class DatabaseUnavailable(DatabaseError):
    user_message = "FORGE-X can't reach its database right now."


class BusinessRuleError(DatabaseError):
    """A rule enforced by a procedure or trigger (SIGNAL). Its message was
    written by us in procedures.sql/triggers.sql, so it is safe to display."""


class ConstraintViolation(DatabaseError):
    """Duplicate key, CHECK constraint or foreign key failure."""

    user_message = "That change conflicts with existing records."

    @property
    def constraint(self):
        match = re.search(r"(?:key|constraint) '([^']+)'", self.detail or "")
        return match.group(1).split(".")[-1] if match else None


class TransientError(DatabaseError):
    """Deadlock or lock wait timeout: safe to retry the whole transaction."""

    user_message = "The database was busy. Please try again."


def translate_error(err):
    """Map a mysql.connector.Error to a FORGE-X exception."""
    errno = getattr(err, "errno", None)
    text = getattr(err, "msg", None) or str(err)
    if errno == ER_SIGNAL_EXCEPTION:
        return BusinessRuleError(text, errno=errno, detail=text)
    if errno in (ER_DUP_ENTRY, ER_CHECK_CONSTRAINT, ER_ROW_IS_REFERENCED, ER_NO_REFERENCED_ROW):
        return ConstraintViolation(errno=errno, detail=text)
    if errno in (ER_LOCK_DEADLOCK, ER_LOCK_WAIT_TIMEOUT):
        return TransientError(errno=errno, detail=text)
    if isinstance(err, (mysql.connector.errors.InterfaceError, mysql.connector.errors.PoolError)) or errno in (
        errorcode.CR_CONN_HOST_ERROR,
        errorcode.CR_CONNECTION_ERROR,
        errorcode.CR_SERVER_GONE_ERROR,
        errorcode.CR_SERVER_LOST,
        errorcode.ER_ACCESS_DENIED_ERROR,
        errorcode.ER_BAD_DB_ERROR,
    ):
        return DatabaseUnavailable(errno=errno, detail=text)
    return DatabaseError(errno=errno, detail=text)


# ---------------------------------------------------------------------------
# Pool and per-request connection
# ---------------------------------------------------------------------------
def init_app(app):
    app.teardown_appcontext(close_db)


def _get_pool():
    pool = current_app.extensions.get(_POOL_KEY)
    if pool is not None:
        return pool
    with _pool_lock:
        pool = current_app.extensions.get(_POOL_KEY)
        if pool is None:
            cfg = current_app.config
            try:
                pool = pooling.MySQLConnectionPool(
                    pool_name=f"forge_x_{id(current_app._get_current_object())}",
                    pool_size=cfg["MYSQL_POOL_SIZE"],
                    pool_reset_session=True,   # clears session variables between borrowers
                    host=cfg["MYSQL_HOST"],
                    port=cfg["MYSQL_PORT"],
                    user=cfg["MYSQL_USER"],
                    password=cfg["MYSQL_PASSWORD"],
                    database=cfg["MYSQL_DATABASE"],
                    charset="utf8mb4",
                    collation="utf8mb4_0900_ai_ci",
                    autocommit=True,
                    connection_timeout=cfg["MYSQL_CONNECT_TIMEOUT"],
                )
            except mysql.connector.Error as err:
                current_app.logger.error("MySQL connection failed: %s", err)
                raise translate_error(err) from err
            current_app.extensions[_POOL_KEY] = pool
    return pool


def dispose_pool(app):
    """Close every connection in this app's pool (used when a test's app is
    thrown away). mysql-connector opens all pool_size connections as soon as
    the pool is created, so pools that are never closed add up quickly:
    one per test would exhaust MySQL's max_connections (error 1040)."""
    pool = app.extensions.pop(_POOL_KEY, None)
    if pool is not None:
        try:
            pool._remove_connections()      # mysql-connector has no public close-all method
        except Exception:                   # closing is best effort; the process exit frees the rest
            pass


def _client_ip():
    return request.remote_addr if has_request_context() else None


def get_db():
    """Return this request's connection, borrowing one from the pool if needed."""
    if "db_conn" not in g:
        try:
            conn = _get_pool().get_connection()
        except mysql.connector.Error as err:
            current_app.logger.error("Could not borrow a MySQL connection: %s", err)
            raise translate_error(err) from err
        cur = conn.cursor()
        try:
            cur.execute(
                "SET time_zone = %s, @app_user_id = %s, @app_ip = %s",
                (current_app.config["DB_TIME_ZONE"], g.get("audit_user_id"), _client_ip()),
            )
        finally:
            cur.close()
        g.db_conn = conn
    return g.db_conn


def set_audit_user(user_id):
    """Record which FORGE-X user is acting, for database-level audit triggers."""
    g.audit_user_id = user_id
    if "db_conn" in g:
        cur = g.db_conn.cursor()
        try:
            cur.execute("SET @app_user_id = %s", (user_id,))
        finally:
            cur.close()


def close_db(exc=None):
    conn = g.pop("db_conn", None)
    if conn is None:
        return
    try:
        if conn.in_transaction:
            conn.rollback()      # never leave a half-finished transaction in the pool
    except mysql.connector.Error:
        pass
    finally:
        conn.close()             # returns the connection to the pool


# ---------------------------------------------------------------------------
# Query helpers (always parameterized)
# ---------------------------------------------------------------------------
def query_all(sql, params=()):
    """Run a SELECT and return a list of dict rows."""
    cur = get_db().cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        return cur.fetchall()
    except mysql.connector.Error as err:
        raise translate_error(err) from err
    finally:
        cur.close()


def query_one(sql, params=()):
    """Run a SELECT and return the first row as a dict, or None."""
    rows = query_all(sql, params)
    return rows[0] if rows else None


def query_value(sql, params=()):
    """Run a SELECT and return the first column of the first row, or None."""
    row = query_one(sql, params)
    return next(iter(row.values())) if row else None


def execute(sql, params=()):
    """Run one INSERT/UPDATE (autocommitted). Returns (lastrowid, rowcount)."""
    cur = get_db().cursor()
    try:
        cur.execute(sql, params)
        return cur.lastrowid, cur.rowcount
    except mysql.connector.Error as err:
        raise translate_error(err) from err
    finally:
        cur.close()


def call_proc(name, args=()):
    """Call a stored procedure and return its arguments after the call, so
    OUT parameters can be read by position. Pass None for OUT parameters."""
    if not _PROC_NAME.match(name):
        raise ValueError(f"Invalid procedure name: {name!r}")
    conn = get_db()
    if conn.in_transaction:
        # START TRANSACTION inside the procedure would silently commit our work.
        raise RuntimeError("Call stored procedures outside an open transaction.")
    cur = conn.cursor()
    try:
        result = cur.callproc(name, tuple(args))
        for _ in cur.stored_results():   # drain any result sets
            pass
        return result
    except mysql.connector.Error as err:
        raise translate_error(err) from err
    finally:
        cur.close()


@contextlib.contextmanager
def transaction():
    """Run several statements atomically.

        with transaction() as cur:
            cur.execute("SELECT ... FOR UPDATE", (...))
            cur.execute("INSERT ...", (...))

    Commits when the block finishes, rolls back on any exception.
    """
    conn = get_db()
    if conn.in_transaction:
        raise RuntimeError("Nested transactions are not supported.")
    conn.start_transaction()
    cur = conn.cursor(dictionary=True)
    try:
        yield cur
        conn.commit()
    except mysql.connector.Error as err:
        conn.rollback()
        raise translate_error(err) from err
    except BaseException:
        conn.rollback()
        raise
    finally:
        cur.close()


def retry_on_transient(attempts=2):
    """Decorator: rerun a whole transactional function once after a deadlock."""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(1, attempts + 1):
                try:
                    return func(*args, **kwargs)
                except TransientError:
                    if attempt == attempts:
                        raise
                    current_app.logger.warning("Retrying %s after a deadlock", func.__name__)
        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Diagnostics (used by `flask check-db`, /healthz and tests)
# ---------------------------------------------------------------------------
# Triggers are not counted here: information_schema.TRIGGERS only lists
# triggers to accounts holding the TRIGGER privilege, which the least-privilege
# app account deliberately lacks. triggers_active() tests them by behaviour.
EXPECTED_OBJECTS = {"tables": 22, "views": 8, "procedures": 12, "functions": 2}


def check_connection():
    """Return facts about the live database. Raises DatabaseError on failure."""
    info = query_one(
        "SELECT VERSION() AS server_version, CURRENT_USER() AS current_user_name, "
        "DATABASE() AS database_name, @@session.time_zone AS time_zone"
    )
    counts = query_one(
        """
        SELECT
          (SELECT COUNT(*) FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE') AS tables,
          (SELECT COUNT(*) FROM information_schema.VIEWS
            WHERE TABLE_SCHEMA = DATABASE()) AS views,
          (SELECT COUNT(*) FROM information_schema.ROUTINES
            WHERE ROUTINE_SCHEMA = DATABASE() AND ROUTINE_TYPE = 'PROCEDURE') AS procedures,
          (SELECT COUNT(*) FROM information_schema.ROUTINES
            WHERE ROUTINE_SCHEMA = DATABASE() AND ROUTINE_TYPE = 'FUNCTION') AS functions
        """
    )
    info["objects"] = {key: int(value) for key, value in counts.items()}
    numbers = re.findall(r"\d+", info["server_version"])[:3]
    info["version_tuple"] = tuple(int(n) for n in numbers)
    return info


class _ProbeRollback(Exception):
    """Raised on purpose so transaction() rolls back the probe."""


def triggers_active():
    """Prove the triggers are installed using only privileges the app has.

    Inside a transaction that is ALWAYS rolled back, insert a verification
    whose computed hash equals the reference hash. The column default is
    'Failed'; only trigger trg_hv_set_result can turn it into 'Verified'.
    Returns True/False, or None if there is no hash to test against.
    (The rolled-back insert may leave a gap in verification_id numbers.)
    """
    outcome = {}
    try:
        with transaction() as cur:
            cur.execute(
                "SELECT h.hash_id, h.hash_value FROM evidence_hashes h "
                "WHERE NOT EXISTS (SELECT 1 FROM evidence_hashes s WHERE s.supersedes_hash_id = h.hash_id) "
                "ORDER BY h.hash_id LIMIT 1"
            )
            ref = cur.fetchone()
            if ref:
                cur.execute(
                    "INSERT INTO hash_verifications (hash_id, computed_hash, method, notes, verified_by) "
                    "VALUES (%s, %s, 'Manual entry', 'check-db trigger probe (rolled back)', "
                    "(SELECT MIN(user_id) FROM users))",
                    (ref["hash_id"], ref["hash_value"]),
                )
                cur.execute("SELECT result FROM hash_verifications WHERE verification_id = LAST_INSERT_ID()")
                outcome["result"] = cur.fetchone()["result"]
            raise _ProbeRollback()
    except _ProbeRollback:
        pass
    if "result" not in outcome:
        return None
    return outcome["result"] == "Verified"


def can_delete_audit_logs():
    """True if the connected account has DELETE on audit_logs (it should not).
    `WHERE 1 = 0` matches no rows, so nothing is ever deleted."""
    try:
        execute("DELETE FROM audit_logs WHERE 1 = 0")
        return True
    except DatabaseError as err:
        if err.errno == ER_TABLEACCESS_DENIED:
            return False
        raise
