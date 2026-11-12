import math
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, time as dtime
from decimal import Decimal
from pathlib import Path

import duckdb

ROW_CAP = 500


class QueryTimeout(Exception):
    """The query ran longer than its time limit and was interrupted."""


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list]
    row_count: int
    truncated: bool
    ms: float


def connect(path: str | Path) -> duckdb.DuckDBPyConnection:
    """Open the database read-only and lock down file access and settings."""
    con = duckdb.connect(str(path), read_only=True)
    con.execute("SET enable_external_access = false")
    con.execute("SET lock_configuration = true")
    return con


def _json_safe(value):
    if isinstance(value, (datetime, date, dtime)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return round(value.total_seconds() / 86400, 2)
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _strip_trailing(sql: str) -> str:
    """Drop trailing semicolons and trailing `--` line comments."""
    body = sql.strip()
    while True:
        prev = body
        body = body.rstrip().rstrip(";").rstrip()
        last_nl = body.rfind("\n") + 1
        line = body[last_nl:]
        pos = line.find("--")
        while pos != -1 and line[:pos].count("'") % 2 == 1:
            pos = line.find("--", pos + 2)
        if pos != -1:
            body = body[: last_nl + pos]
        if body == prev:
            return body


def run_query(
    con: duckdb.DuckDBPyConnection, sql: str, timeout_s: float = 5.0
) -> QueryResult:
    """Run SQL with a row cap and a timeout. Does not call the guard."""
    body = _strip_trailing(sql)
    wrapped = f"SELECT * FROM (\n{body}\n) LIMIT {ROW_CAP + 1}"
    timed_out = threading.Event()

    def _interrupt() -> None:
        timed_out.set()
        con.interrupt()

    timer = threading.Timer(timeout_s, _interrupt)
    start = time.perf_counter()
    timer.start()
    try:
        cur = con.execute(wrapped)
        columns = [d[0] for d in cur.description]
        raw = cur.fetchall()
    except duckdb.Error as exc:
        if timed_out.is_set():
            raise QueryTimeout(f"Query exceeded {timeout_s} seconds") from exc
        raise
    finally:
        timer.cancel()
    ms = (time.perf_counter() - start) * 1000
    truncated = len(raw) > ROW_CAP
    raw = raw[:ROW_CAP]
    rows = [[_json_safe(v) for v in row] for row in raw]
    return QueryResult(columns, rows, len(rows), truncated, ms)
