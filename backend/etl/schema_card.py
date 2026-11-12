"""Generate the schema card: the only view of the data the LLM ever gets.

It lists each column with its type, description and null rate, plus the exact
category values (with counts) for low-cardinality text columns, so the model
filters on real values like 'Pot Hole' instead of guessing 'pothole'.
"""
import json
from pathlib import Path

import duckdb

from . import config

MAX_ENUM = 400       # text columns with at most this many distinct values get a full value list
TOP_FOR_ZIP = 40     # ZIPs are listed by volume, capped
SAMPLES = 3          # example values for high-cardinality text columns
NO_SAMPLES = {"case_number"}  # IDs add nothing to the prompt
# Low-cardinality but not useful to filter on; listing every value would roughly double
# the prompt (status_description alone was ~17K characters), so show examples only.
EXAMPLES_ONLY = {"status_description", "census_tract"}

# Rules the model must follow; these become part of the prompt verbatim.
QUERY_RULES = [
    "Query only the table requests_311. Use DuckDB SQL.",
    "For relative dates ('last 30 days', 'this year'), anchor to (SELECT max(created_at) FROM requests_311), never now() or current_date: the data is a snapshot.",
    "Filter categorical columns with exact values from the 'values' lists below. Use ILIKE only when no listed value fits.",
    "When counting requests, exclude duplicates with WHERE duplicate_request IS NOT TRUE, unless the question asks about duplicates.",
    "days_to_close is null for open requests; exclude nulls when averaging and prefer median() over avg() for durations.",
    "Data starts in May 2024. Say so if a question asks about earlier dates.",
    "The most recent month is incomplete. For monthly trends, exclude it or say it is partial.",
]


def build_schema_card(db_path: Path, metadata: dict, plan: list[dict]) -> dict:
    descriptions = {p["name"]: p["description"] for p in plan}
    descriptions["days_to_close"] = "Days between created_at and closed_at (derived; null if open or if closed before created)."

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        t = config.TABLE
        row_count, min_created, max_created = con.execute(
            f"SELECT count(*), min(created_at), max(created_at) FROM {t}"
        ).fetchone()
        columns = []
        for name, dtype in con.execute(f"SELECT column_name, column_type FROM (DESCRIBE {t})").fetchall():
            col = {"name": name, "type": dtype, "description": descriptions.get(name, "")}
            col["null_pct"] = round(
                con.execute(f'SELECT 100.0 * count(*) FILTER (WHERE "{name}" IS NULL) / count(*) FROM {t}').fetchone()[0], 1
            )
            if dtype == "VARCHAR":
                distinct = con.execute(f'SELECT count(DISTINCT "{name}") FROM {t}').fetchone()[0]
                col["distinct"] = distinct
                if name == "zip":
                    col["values"] = _value_counts(con, t, name, TOP_FOR_ZIP)
                    col["values_note"] = f"top {TOP_FOR_ZIP} by request volume"
                elif distinct <= MAX_ENUM and name not in NO_SAMPLES | EXAMPLES_ONLY:
                    col["values"] = _value_counts(con, t, name, None)
                elif name not in NO_SAMPLES:
                    col["examples"] = [r[0] for r in con.execute(
                        f'SELECT DISTINCT "{name}" FROM {t} WHERE "{name}" IS NOT NULL LIMIT {SAMPLES}'
                    ).fetchall()]
            elif dtype == "BOOLEAN":
                col["values"] = _value_counts(con, t, name, None)
            elif dtype in ("DOUBLE", "TIMESTAMP", "BIGINT", "INTEGER"):
                lo, hi = con.execute(f'SELECT min("{name}"), max("{name}") FROM {t}').fetchone()
                col["min"], col["max"] = _fmt(lo), _fmt(hi)
            columns.append(col)
    finally:
        con.close()

    return {
        "table": config.TABLE,
        "source": metadata.get("name"),
        "source_url": metadata.get("dataset_url"),
        "row_count": row_count,
        "created_at_range": [_fmt(min_created), _fmt(max_created)],
        "rules": QUERY_RULES,
        "columns": columns,
    }


def render_markdown(card: dict) -> str:
    """Compact text form of the card, used directly in the LLM prompt."""
    lines = [
        f"Table {card['table']}: {card['row_count']:,} Buffalo 311 service requests, "
        f"created {card['created_at_range'][0]} to {card['created_at_range'][1]}.",
        "",
        "Rules:",
        *[f"- {r}" for r in card["rules"]],
        "",
        "Columns:",
    ]
    for c in card["columns"]:
        line = f"- {c['name']} ({c['type']}, {c['null_pct']}% null)"
        if c["description"]:
            desc = c["description"].rstrip()
            line += f": {desc}" + ("" if desc.endswith((".", ")")) else ".")
        if c.get("min") is not None:
            line += f" Range {c['min']} to {c['max']}."
        lines.append(line)
        if c.get("values"):
            note = f" ({c['values_note']})" if "values_note" in c else ""
            vals = "; ".join(f"{v['value']!r} {v['count']:,}" for v in c["values"])
            lines.append(f"  values{note}: {vals}")
        elif c.get("examples"):
            lines.append(f"  examples: {'; '.join(repr(e) for e in c['examples'])}")
    return "\n".join(lines) + "\n"


def write_schema_card(card: dict, json_path: Path, md_path: Path) -> None:
    json_path.write_text(json.dumps(card, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(card), encoding="utf-8")


def _value_counts(con, table: str, name: str, limit: int | None) -> list[dict]:
    lim = f"LIMIT {limit}" if limit else ""
    rows = con.execute(
        f'SELECT "{name}", count(*) AS n FROM {table} WHERE "{name}" IS NOT NULL '
        f'GROUP BY 1 ORDER BY n DESC, 1 {lim}'
    ).fetchall()
    return [{"value": v, "count": n} for v, n in rows]


def _fmt(x):
    if x is None:
        return None
    if hasattr(x, "isoformat"):
        return x.isoformat(sep=" ", timespec="minutes")
    return round(x, 5) if isinstance(x, float) else x
