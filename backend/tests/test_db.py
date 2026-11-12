import duckdb
import pytest

from app import db


@pytest.fixture
def con(fixture_db_path):
    c = db.connect(fixture_db_path)
    yield c
    c.close()


def test_reads_fixture_table(con):
    n = con.execute("SELECT count(*) FROM requests_311").fetchone()[0]
    assert n == 30


def test_fixture_coverage(con):
    types = {r[0] for r in con.execute("SELECT DISTINCT request_type FROM requests_311").fetchall()}
    assert {"Pothole Issue", "Garbage Missed Pick Up"} <= types and len(types) >= 5
    assert con.execute("SELECT count(DISTINCT council_district) FROM requests_311").fetchone()[0] >= 3
    statuses = {r[0] for r in con.execute("SELECT DISTINCT status FROM requests_311").fetchall()}
    assert {"Closed", "New", "In Progress"} <= statuses
    assert con.execute("SELECT count(*) FROM requests_311 WHERE duplicate_request").fetchone()[0] > 0
    assert con.execute("SELECT count(*) FROM requests_311 WHERE closed_at IS NULL AND days_to_close IS NULL").fetchone()[0] > 0
    assert con.execute("SELECT count(DISTINCT date_trunc('month', created_at)) FROM requests_311").fetchone()[0] >= 2


def test_open_and_closed_rows_span_request_types(con):
    open_types = {r[0] for r in con.execute(
        "SELECT DISTINCT request_type FROM requests_311 WHERE closed_at IS NULL").fetchall()}
    assert len(open_types) >= 3
    for (t,) in con.execute("SELECT DISTINCT request_type FROM requests_311").fetchall():
        n_open, n_closed = con.execute(
            "SELECT count(*) FILTER (WHERE closed_at IS NULL), count(*) FILTER (WHERE closed_at IS NOT NULL) "
            "FROM requests_311 WHERE request_type = ?", [t]).fetchone()
        assert n_open > 0 and n_closed > 0, t


def test_cannot_read_files(con, tmp_path):
    csv = tmp_path / "x.csv"
    csv.write_text("a\n1\n")
    with pytest.raises(duckdb.Error):
        con.execute(f"SELECT * FROM read_csv('{csv}')").fetchall()


@pytest.mark.parametrize(
    "sql",
    [
        "SET enable_external_access = true",
        "SET lock_configuration = false",
        "CREATE TABLE t (a INT)",
        "INSERT INTO requests_311 (case_number) VALUES ('x')",
    ],
)
def test_cannot_change_settings_or_write(con, sql):
    with pytest.raises(duckdb.Error):
        con.execute(sql)


@pytest.mark.realdb
def test_real_db_has_rows():
    from tests.conftest import REAL_DB

    con = db.connect(REAL_DB)
    try:
        assert con.execute("SELECT count(*) FROM requests_311").fetchone()[0] > 0
    finally:
        con.close()
