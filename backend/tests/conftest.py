import sys
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import pytest

# Make `etl` importable when running pytest from backend/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REAL_DB = Path(__file__).resolve().parents[1] / "data" / "ask_the_city.duckdb"

COLUMNS = """
    case_number VARCHAR, created_at TIMESTAMP, closed_at TIMESTAMP,
    request_type VARCHAR, status VARCHAR, status_description VARCHAR,
    department VARCHAR, division VARCHAR, council_district VARCHAR,
    planningneighborhood VARCHAR, planningsector VARCHAR, policedistrict VARCHAR,
    census_tract VARCHAR, street VARCHAR, assessedstreet VARCHAR, city VARCHAR,
    state VARCHAR, zip VARCHAR, latitude DOUBLE, longitude DOUBLE,
    duplicate_request BOOLEAN, days_to_close DOUBLE
"""

TYPES = [
    "Pothole Issue",
    "Garbage Missed Pick Up",
    "General Parking Issue(s)",
    "Replacement Garbage Totes Request",
    "Housing or Building Violations(Exterior)",
]
DISTRICTS = ["LOVEJOY", "FILLMORE", "NIAGARA", "ELLICOTT"]


def pytest_configure(config):
    config.addinivalue_line("markers", "realdb: needs the real ask_the_city.duckdb")


def pytest_collection_modifyitems(config, items):
    if REAL_DB.exists():
        return
    skip = pytest.mark.skip(reason="backend/data/ask_the_city.duckdb is missing")
    for item in items:
        if "realdb" in item.keywords:
            item.add_marker(skip)


def _rows():
    start = datetime(2026, 9, 20, 9, 0)
    rows = []
    for i in range(30):
        created = start + timedelta(days=i, hours=i % 5)
        is_open = i % 3 == 0
        status = "New" if i % 6 == 0 else "In Progress" if is_open else "Closed"
        days = None if is_open else float(1 + i % 7)
        closed = None if is_open else created + timedelta(days=days)
        rows.append(
            (
                f"CASE-{i:04d}", created, closed, TYPES[i % 5], status, None,
                "Public Works", "Streets", DISTRICTS[i % 4], "Elmwood", "Sector A",
                "D1", "1001", "Main St", "Main St", "Buffalo", "NY", "14201",
                42.88 + i * 0.001, -78.87 - i * 0.001, i % 7 == 3, days,
            )
        )
    return rows


@pytest.fixture(scope="session")
def fixture_db_path(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("fixture_db") / "fixture.duckdb"
    con = duckdb.connect(str(path))
    con.execute(f"CREATE TABLE requests_311 ({COLUMNS})")
    con.executemany(
        f"INSERT INTO requests_311 VALUES ({', '.join('?' * 22)})", _rows()
    )
    con.close()
    return path
