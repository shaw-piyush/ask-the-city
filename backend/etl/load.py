"""Build the cleaned DuckDB table `requests_311` from raw JSONL + Socrata metadata.

Every source field is read as text from the raw JSON, then cast explicitly.
Fields we know get curated names and cleaning; any other field is kept with a
snake_case name and a type derived from Socrata's metadata, so a schema change
upstream adds a column instead of breaking the build.
"""
import re
from pathlib import Path

import duckdb

from . import config

# Socrata field -> (column name, SQL over the raw text value `v`)
CURATED = {
    "casenumber": ("case_number", "NULLIF(TRIM(v), '')"),
    "createddate": ("created_at", "TRY_CAST(v AS TIMESTAMP)"),
    "closeddate": ("closed_at", "TRY_CAST(v AS TIMESTAMP)"),
    # Old 311 data suffixed types with "(Req_Serv)"; strip it if present, collapse spaces.
    "type": (
        "request_type",
        "NULLIF(TRIM(regexp_replace(regexp_replace(v, '\\(\\s*req_serv\\s*\\)', '', 'gi'), '\\s+', ' ', 'g')), '')",
    ),
    "status": ("status", "NULLIF(TRIM(v), '')"),
    "statusdescription": ("status_description", "NULLIF(TRIM(v), '')"),
    "zip": ("zip", "NULLIF(regexp_extract(v, '(\\d{5})', 1), '')"),
    "latitude": ("latitude", "TRY_CAST(v AS DOUBLE)"),
    "longitude": ("longitude", "TRY_CAST(v AS DOUBLE)"),
}
# The source writes the literal string 'UNKNOWN' instead of leaving these empty.
for _field in ("council_district", "planningneighborhood", "planningsector", "policedistrict"):
    CURATED[_field] = (_field, "CASE WHEN UPPER(TRIM(v)) IN ('', 'UNKNOWN') THEN NULL ELSE TRIM(v) END")

# Categorical columns where the source mixes casing ('EAST' vs 'East', 'buffalo' vs 'Buffalo').
# Each value is rewritten to its most common spelling.
CANONICAL_CASE = (
    "request_type", "status", "department", "division", "council_district",
    "planningneighborhood", "planningsector", "policedistrict", "city", "state",
)

GENERIC_CAST = {
    "number": "TRY_CAST(v AS DOUBLE)",
    "calendar_date": "TRY_CAST(v AS TIMESTAMP)",
    "checkbox": "TRY_CAST(v AS BOOLEAN)",
}
SKIP_TYPES = {"point", "location", "multipolygon", "polygon", "line", "multiline", "multipoint"}
# Address-level fields would pin a complaint (noise, housing) to one house; the demo
# never needs them. Census blocks are too fine-grained to chart. Keep census_tract.
DROP_FIELDS = {
    "assessednumber",
    "propertyid",
    "reportedlocation",
    "secondarystreet",
    "census_block",
    "census_block_group",
}
# Defensive: never load anything that looks like a resident's personal details.
PII_PATTERN = re.compile(r"(first_?name|last_?name|full_?name|caller|phone|email|contact)", re.IGNORECASE)


def snake(field: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", field.lower()).strip("_")


def column_plan(metadata: dict) -> list[dict]:
    """Decide the output column, SQL expression and description for each source field."""
    plan = []
    for col in metadata["columns"]:
        field, kind = col["field"], col["type"]
        if field in DROP_FIELDS:
            continue
        if field in CURATED:
            name, expr = CURATED[field]
        elif kind in SKIP_TYPES or PII_PATTERN.search(field):
            continue
        else:
            name, expr = snake(field), GENERIC_CAST.get(kind, "NULLIF(TRIM(v), '')")
        plan.append({"source": field, "name": name, "expr": expr, "description": col["description"]})
    return plan


def build_db(raw_jsonl: Path, metadata: dict, db_path: Path) -> dict:
    """Create the DuckDB file atomically and return cleaning stats."""
    plan = column_plan(metadata)
    names = {p["name"] for p in plan}
    missing = {"case_number", "created_at", "request_type"} - names
    if missing:
        raise RuntimeError(f"Source is missing required fields: {sorted(missing)}")

    tmp = db_path.with_suffix(".building.duckdb")
    tmp.unlink(missing_ok=True)
    con = duckdb.connect(str(tmp))
    try:
        con.execute(
            "CREATE TEMP TABLE raw AS SELECT json AS j FROM read_ndjson_objects(?)",
            [str(raw_jsonl)],
        )
        raw_rows = con.execute("SELECT count(*) FROM raw").fetchone()[0]

        selects = []
        for p in plan:
            value_sql = "(j ->> " + _quote(p["source"]) + ")"
            selects.append(_bind(p["expr"], value_sql) + " AS " + p["name"])
        con.execute(f"CREATE TEMP TABLE typed AS SELECT {', '.join(selects)} FROM raw")

        has_geo = {"latitude", "longitude"} <= names
        lat_lo, lat_hi = config.LAT_RANGE
        lon_lo, lon_hi = config.LON_RANGE
        in_city = f"latitude BETWEEN {lat_lo} AND {lat_hi} AND longitude BETWEEN {lon_lo} AND {lon_hi}"
        # Some source rows store latitude and longitude swapped; swap them back.
        swapped = f"longitude BETWEEN {lat_lo} AND {lat_hi} AND latitude BETWEEN {lon_lo} AND {lon_hi}"
        out_cols = []
        for p in plan:
            if has_geo and p["name"] == "latitude":
                out_cols.append(f"CASE WHEN {in_city} THEN latitude WHEN {swapped} THEN longitude END AS latitude")
            elif has_geo and p["name"] == "longitude":
                out_cols.append(f"CASE WHEN {in_city} THEN longitude WHEN {swapped} THEN latitude END AS longitude")
            else:
                out_cols.append(p["name"])

        days = ""
        if "closed_at" in names:
            days = (
                ", CASE WHEN closed_at >= created_at "
                "THEN round(date_diff('second', created_at, closed_at) / 86400.0, 2) END AS days_to_close"
            )

        con.execute(
            f"""
            CREATE TABLE {config.TABLE} AS
            SELECT {', '.join(out_cols)}{days}
            FROM typed
            WHERE case_number IS NOT NULL AND created_at IS NOT NULL
            QUALIFY row_number() OVER (PARTITION BY case_number ORDER BY created_at DESC) = 1
            ORDER BY created_at
            """
        )

        stats = {"raw_rows": raw_rows}
        stats["loaded_rows"] = con.execute(f"SELECT count(*) FROM {config.TABLE}").fetchone()[0]
        stats["dropped_missing_id_or_date"] = con.execute(
            "SELECT count(*) FROM typed WHERE case_number IS NULL OR created_at IS NULL"
        ).fetchone()[0]
        stats["dropped_duplicates"] = raw_rows - stats["dropped_missing_id_or_date"] - stats["loaded_rows"]
        if has_geo:
            stats["swapped_coords_fixed"] = con.execute(
                f"SELECT count(*) FROM typed WHERE {swapped}"
            ).fetchone()[0]
            stats["nulled_out_of_bounds_coords"] = con.execute(
                f"SELECT count(*) FROM typed WHERE latitude IS NOT NULL AND NOT ({in_city}) AND NOT ({swapped})"
            ).fetchone()[0]
        stats["case_variants_fixed"] = _canonicalize_case(con, [c for c in CANONICAL_CASE if c in names])
        if "closed_at" in names:
            stats["closed_before_created"] = con.execute(
                "SELECT count(*) FROM typed WHERE closed_at < created_at"
            ).fetchone()[0]
        con.execute("CHECKPOINT")
    finally:
        con.close()

    tmp.replace(db_path)  # the API never sees a half-built database
    return stats


def _canonicalize_case(con, columns: list[str]) -> int:
    """Rewrite case variants of each value to its most common spelling. Returns rows changed."""
    changed = 0
    for col in columns:
        canon = f"""
            SELECT upper({col}) AS k, arg_max({col}, n) AS canon
            FROM (SELECT {col}, count(*) AS n FROM {config.TABLE} WHERE {col} IS NOT NULL GROUP BY 1)
            GROUP BY 1
        """
        changed += con.execute(
            f"SELECT count(*) FROM {config.TABLE} t JOIN ({canon}) m "
            f"ON upper(t.{col}) = m.k WHERE t.{col} <> m.canon"
        ).fetchone()[0]
        con.execute(
            f"UPDATE {config.TABLE} SET {col} = m.canon FROM ({canon}) m "
            f"WHERE upper({config.TABLE}.{col}) = m.k AND {config.TABLE}.{col} <> m.canon"
        )
    return changed


def _bind(expr: str, value_sql: str) -> str:
    """Substitute the standalone token `v` in an expression template."""
    return re.sub(r"\bv\b", lambda _: value_sql, expr)


def _quote(field: str) -> str:
    """Quote a Socrata field name as a SQL string literal (field names come from metadata)."""
    return "'" + field.replace("'", "''") + "'"
