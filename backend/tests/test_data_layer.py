"""Unit tests for the ETL cleaning rules and schema card.

Uses a tiny hand-written fixture to exercise edge cases only; the app itself
always runs on the real Socrata download.
Run from backend/:  python -m pytest -q
"""
import json

import duckdb
import pytest

from etl.load import build_db, column_plan
from etl.schema_card import build_schema_card, render_markdown

METADATA = {
    "name": "fixture",
    "dataset_url": "https://example.test/d/fixture",
    "columns": [
        {"field": "casenumber", "type": "text", "description": "case id"},
        {"field": "createddate", "type": "calendar_date", "description": "created"},
        {"field": "closeddate", "type": "calendar_date", "description": "closed"},
        {"field": "type", "type": "text", "description": "request type"},
        {"field": "status", "type": "text", "description": "status"},
        {"field": "zip", "type": "text", "description": "zip"},
        {"field": "latitude", "type": "number", "description": "lat"},
        {"field": "longitude", "type": "number", "description": "lon"},
        {"field": "council_district", "type": "text", "description": "council district"},
        {"field": "duplicate_request", "type": "checkbox", "description": "duplicate flag"},
        {"field": "reportedlocation", "type": "text", "description": "address as reported"},
        {"field": "assessednumber", "type": "text", "description": "house number"},
        {"field": "propertyid", "type": "text", "description": "SBL number"},
        {"field": "census_block", "type": "text", "description": "census block"},
        {"field": "census_tract", "type": "text", "description": "census tract"},
        {"field": "planningsector", "type": "text", "description": "planning sector"},
        {"field": "location", "type": "point", "description": "geo point"},
        {"field": "callername", "type": "text", "description": "should never load"},
    ],
}

ROWS = [
    # normal row, suffix to strip, ZIP+4
    {"casenumber": "A1", "createddate": "2024-05-13T10:00:00.000", "closeddate": "2024-05-15T10:00:00.000",
     "type": "Pot Hole (Req_Serv)", "status": "Closed", "zip": "14201-1234",
     "latitude": "42.9", "longitude": "-78.85", "council_district": "Niagara",
     "duplicate_request": False, "reportedlocation": "123 Main St", "assessednumber": "123",
     "propertyid": "100.10-1-1", "census_block": "1001", "census_tract": "35",
     "location": {"type": "Point", "coordinates": [-78.85, 42.9]}, "callername": "Jane Doe"},
    # duplicate case number: the later created_at wins
    {"casenumber": "A1", "createddate": "2024-05-14T10:00:00.000", "type": "Pot Hole", "status": "Open",
     "duplicate_request": True},
    # missing created date: dropped
    {"casenumber": "A2", "type": "Rodents", "status": "Open"},
    # out-of-bounds coordinates (0,0) and closed before created
    {"casenumber": "A3", "createddate": "2024-06-01T09:00:00.000", "closeddate": "2024-05-31T09:00:00.000",
     "type": "  Rodents   ", "status": "Closed", "zip": "", "latitude": "0", "longitude": "0"},
    # sparse row: keys missing entirely
    {"casenumber": "A4", "createddate": "2024-07-01T08:30:00.000", "type": "Streetlights"},
    # swapped lat/lon (seen 10,126 times in the real data), 'UNKNOWN' district, case variants
    {"casenumber": "A5", "createddate": "2024-07-02T08:30:00.000", "type": "Streetlights",
     "latitude": "-78.83", "longitude": "42.87", "council_district": "UNKNOWN", "planningsector": "East"},
    {"casenumber": "A6", "createddate": "2024-07-03T08:30:00.000", "type": "Streetlights",
     "planningsector": "EAST"},
    {"casenumber": "A7", "createddate": "2024-07-04T08:30:00.000", "type": "Streetlights",
     "planningsector": "EAST"},
]


@pytest.fixture()
def built(tmp_path):
    raw = tmp_path / "requests.jsonl"
    raw.write_text("\n".join(json.dumps(r) for r in ROWS) + "\n", encoding="utf-8")
    db = tmp_path / "test.duckdb"
    stats = build_db(raw, METADATA, db)
    con = duckdb.connect(str(db), read_only=True)
    yield con, stats, db
    con.close()


def rows(con, sql):
    return con.execute(sql).fetchall()


def test_counts_and_stats(built):
    con, stats, _ = built
    assert stats["raw_rows"] == 8
    assert stats["dropped_missing_id_or_date"] == 1
    assert stats["dropped_duplicates"] == 1
    assert stats["loaded_rows"] == 6
    assert stats["swapped_coords_fixed"] == 1
    assert stats["nulled_out_of_bounds_coords"] == 1
    assert stats["closed_before_created"] == 1
    assert stats["case_variants_fixed"] == 1


def test_swapped_coords_are_fixed(built):
    con, _, _ = built
    assert rows(con, "SELECT latitude, longitude FROM requests_311 WHERE case_number = 'A5'") == [(42.87, -78.83)]


def test_unknown_becomes_null_and_case_is_canonical(built):
    con, _, _ = built
    assert rows(con, "SELECT council_district FROM requests_311 WHERE case_number = 'A5'") == [(None,)]
    sectors = {r[0] for r in rows(con, "SELECT planningsector FROM requests_311 WHERE planningsector IS NOT NULL")}
    assert sectors == {"EAST"}


def test_dedup_keeps_latest(built):
    con, _, _ = built
    assert rows(con, "SELECT status FROM requests_311 WHERE case_number = 'A1'") == [("Open",)]


def test_type_normalization(built):
    con, _, _ = built
    types = {r[0] for r in rows(con, "SELECT request_type FROM requests_311")}
    assert types == {"Pot Hole", "Rodents", "Streetlights"}


def test_zip_and_geo_cleaning(built):
    con, _, _ = built
    a3 = rows(con, "SELECT zip, latitude, longitude, days_to_close FROM requests_311 WHERE case_number='A3'")
    assert a3 == [(None, None, None, None)]


def test_types_are_real(built):
    con, _, _ = built
    types = dict(rows(con, "SELECT column_name, column_type FROM (DESCRIBE requests_311)"))
    assert types["created_at"] == "TIMESTAMP"
    assert types["latitude"] == "DOUBLE"
    assert types["days_to_close"] == "DOUBLE"


def test_columns_kept_and_dropped(built):
    con, _, _ = built
    cols = {r[0] for r in rows(con, "SELECT column_name FROM (DESCRIBE requests_311)")}
    assert {"council_district", "census_tract", "duplicate_request"} <= cols
    dropped = {"callername", "location", "reportedlocation", "reported_location",
               "assessednumber", "propertyid", "census_block"}
    assert not dropped & cols


def test_duplicate_flag_is_boolean(built):
    con, _, _ = built
    assert rows(con, "SELECT duplicate_request FROM requests_311 WHERE case_number = 'A1'") == [(True,)]


def test_missing_required_field_fails(tmp_path):
    meta = {"columns": [c for c in METADATA["columns"] if c["field"] != "type"]}
    raw = tmp_path / "r.jsonl"
    raw.write_text(json.dumps(ROWS[0]) + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="request_type"):
        build_db(raw, meta, tmp_path / "x.duckdb")


def test_schema_card(built):
    _, _, db = built
    card = build_schema_card(db, METADATA, column_plan(METADATA))
    assert card["row_count"] == 6
    by_name = {c["name"]: c for c in card["columns"]}
    assert {v["value"] for v in by_name["request_type"]["values"]} == {"Pot Hole", "Rodents", "Streetlights"}
    assert "values" not in by_name["case_number"] and "examples" not in by_name["case_number"]
    md = render_markdown(card)
    assert "'Pot Hole' 1" in md
    assert "max(created_at)" in md
    assert "duplicate_request IS NOT TRUE" in md
    assert {v["value"] for v in by_name["duplicate_request"]["values"]} == {True}
