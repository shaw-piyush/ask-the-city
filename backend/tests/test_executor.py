import json
import time

import duckdb
import pytest

from app import db


@pytest.fixture
def con(fixture_db_path):
    c = db.connect(fixture_db_path)
    yield c
    c.close()


def test_normal_result(con):
    r = db.run_query(con, "SELECT request_type, count(*) AS n FROM requests_311 GROUP BY 1 ORDER BY 1")
    assert r.columns == ["request_type", "n"]
    assert r.row_count == len(r.rows) == 5
    assert not r.truncated
    assert r.ms >= 0


def test_truncation_at_501(con):
    r = db.run_query(con, "SELECT * FROM range(501)")
    assert r.truncated and r.row_count == 500 and len(r.rows) == 500


def test_exactly_500_not_truncated(con):
    r = db.run_query(con, "SELECT * FROM range(500)")
    assert not r.truncated and r.row_count == 500


def test_timeout_and_connection_survives(con):
    slow = "SELECT count(*) FROM range(100000000) a, range(100000000) b"
    start = time.perf_counter()
    with pytest.raises(db.QueryTimeout):
        db.run_query(con, slow, timeout_s=0.2)
    assert time.perf_counter() - start < 1.2
    assert db.run_query(con, "SELECT 1").rows == [[1]]


def test_json_safe_values(con):
    r = db.run_query(
        con,
        "SELECT DATE '2026-01-02' AS d, TIMESTAMP '2026-01-02 03:04:05' AS t, "
        "CAST(1.25 AS DECIMAL(10,2)) AS x",
    )
    assert r.rows == [["2026-01-02", "2026-01-02T03:04:05", 1.25]]
    assert isinstance(r.rows[0][2], float)
    json.dumps(r.rows, allow_nan=False)


def test_trailing_semicolon(con):
    assert db.run_query(con, "SELECT 1 AS a;  ").rows == [[1]]


def test_trailing_line_comment(con):
    assert db.run_query(con, "SELECT 1 AS a -- note").rows == [[1]]
    assert db.run_query(con, "SELECT 1 AS a; -- note").rows == [[1]]


def test_sql_error_propagates(con):
    with pytest.raises(duckdb.Error):
        db.run_query(con, "SELECT nope FROM requests_311")


def test_interval_becomes_days(con):
    r = db.run_query(con, "SELECT INTERVAL 36 HOUR AS i, avg(closed_at - created_at) AS a FROM requests_311")
    assert r.rows[0][0] == 1.5
    assert isinstance(r.rows[0][1], float)
    json.dumps(r.rows, allow_nan=False)


def test_timestamptz_is_iso_string(con):
    r = db.run_query(con, "SELECT now() AS n")
    assert isinstance(r.rows[0][0], str)
    json.dumps(r.rows, allow_nan=False)


def test_nan_and_infinity_become_null(con):
    r = db.run_query(
        con, "SELECT 'NaN'::DOUBLE AS a, 'Infinity'::DOUBLE AS b, '-Infinity'::DOUBLE AS c, 1.5::DOUBLE AS d"
    )
    assert r.rows == [[None, None, None, 1.5]]
    json.dumps(r.rows, allow_nan=False)
