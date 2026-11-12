import pytest

from app.guard import GuardResult, check_sql

ALLOWED = [
    "SELECT * FROM requests_311",
    "select count(*) from REQUESTS_311 where status = 'New'",
    "WITH a AS (SELECT request_type, count(*) n FROM requests_311 GROUP BY 1) SELECT * FROM a",
    "WITH a AS (SELECT 1 x FROM requests_311), b AS (SELECT 2 x FROM requests_311) "
    "SELECT a.x FROM a JOIN b ON a.x = b.x",
    "SELECT * FROM (SELECT request_type FROM requests_311) t",
    "SELECT * FROM requests_311 WHERE council_district IN (SELECT council_district FROM requests_311)",
    "SELECT request_type, row_number() OVER (PARTITION BY status ORDER BY created_at) FROM requests_311",
    "SELECT date_trunc('month', created_at) m, median(days_to_close) FROM requests_311 GROUP BY 1",
    "SELECT * FROM requests_311 WHERE request_type = 'DROP TABLE'",
    "SELECT * FROM requests_311 WHERE request_type = 'read_csv(x); DELETE'",
    "SELECT * FROM requests_311;",
    "SELECT 1 FROM requests_311 -- DROP TABLE requests_311",
]

REJECTED = [
    "SELECT current_setting('temp_directory') FROM requests_311",
    "SELECT getenv('HOME')",
    "SELECT * FROM requests_311 WHERE getenv('X') = 'y'",
    "SELECT read_text('/etc/passwd')",
    "SELECT read_blob('/etc/hostname')",
    "SELECT which_secret('s3://x', 's3')",
    "SELECT version()",
    "SELECT upper(read_text('/x')) FROM requests_311",
    "SELECT glob('*')",
    "SELECT duckdb_settings()",
    "SELECT pragma_database_list()",
    "SELECT query('SELECT 1')",
    "SELECT query_table('requests_311')",
    "SELECT * FROM requests_311 WHERE length(read_text('/x')) > 0",
    "SELECT 1; SELECT 2",
    "SELECT 1 FROM requests_311; DROP TABLE requests_311",
    "SELECT 1; -- DROP\nDROP TABLE requests_311",
    "DROP TABLE requests_311",
    "INSERT INTO requests_311 VALUES (1)",
    "UPDATE requests_311 SET status = 'x'",
    "DELETE FROM requests_311",
    "ALTER TABLE requests_311 ADD COLUMN x INT",
    "CREATE TABLE t AS SELECT * FROM requests_311",
    "CALL pragma_version()",
    "PRAGMA database_list",
    "SET enable_external_access = true",
    "ATTACH 'x.db'",
    "DETACH x",
    "COPY requests_311 TO 'out.csv'",
    "EXPORT DATABASE 'dir'",
    "INSTALL httpfs",
    "LOAD httpfs",
    "SELECT * FROM other_table",
    "SELECT * FROM main.requests_311",
    "SELECT * FROM information_schema.tables",
    "SELECT * FROM read_csv('a.csv')",
    "SELECT * FROM read_parquet('a.parquet')",
    "SELECT * FROM read_json_auto('a.json')",
    "SELECT * FROM glob('*')",
    "WITH a AS (SELECT * FROM read_csv('a.csv')) SELECT * FROM a",
    "SELECT * FROM (SELECT * FROM read_csv('a.csv')) t",
    "SELECT * FROM requests_311 WHERE id IN (SELECT * FROM read_csv('a.csv'))",
    "SELECT * FROM requests_311 JOIN read_csv('a.csv') ON true",
    "SELECT 1 FROM requests_311 WHERE",
    "this is not sql",
    "",
    "   ",
]


@pytest.mark.parametrize("sql", ALLOWED)
def test_allowed(sql):
    result = check_sql(sql)
    assert result == GuardResult(ok=True, reason=None), result


@pytest.mark.parametrize("sql", REJECTED)
def test_rejected(sql):
    result = check_sql(sql)
    assert not result.ok
    assert result.reason


def test_never_raises_on_bad_input():
    for bad in ["\x00", "'unterminated", "((((", "SELECT " * 200]:
        assert isinstance(check_sql(bad), GuardResult)
