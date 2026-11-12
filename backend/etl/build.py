"""One command to refresh the data layer.

Usage (from backend/):
    python -m etl.build              # fetch from Socrata, build DuckDB, write schema card
    python -m etl.build --skip-fetch # rebuild from the last download (no network)
"""
import argparse
import json
from datetime import datetime, timezone

from . import config
from .fetch import fetch_metadata, fetch_rows, make_session
from .load import build_db, column_plan
from .schema_card import build_schema_card, write_schema_card


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skip-fetch", action="store_true")
    args = parser.parse_args()

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    raw = config.RAW_DIR / "requests.jsonl"

    if args.skip_fetch:
        if not raw.exists() or not config.METADATA_PATH.exists():
            raise SystemExit("No previous download found. Run without --skip-fetch first.")
        metadata = json.loads(config.METADATA_PATH.read_text(encoding="utf-8"))
    else:
        print("1/3 Fetching from Socrata ...")
        session = make_session()
        metadata = fetch_metadata(session)
        config.METADATA_PATH.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        fetch_rows(session, raw)

    print("2/3 Building DuckDB ...")
    stats = build_db(raw, metadata, config.DB_PATH)

    print("3/3 Writing schema card ...")
    card = build_schema_card(config.DB_PATH, metadata, column_plan(metadata))
    write_schema_card(card, config.SCHEMA_CARD_JSON, config.SCHEMA_CARD_MD)

    updated = metadata.get("rows_updated_at")
    snapshot = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_rows_updated_at": (
            datetime.fromtimestamp(updated, timezone.utc).isoformat(timespec="seconds") if updated else None
        ),
        "source_url": metadata.get("dataset_url"),
        "license": metadata.get("license"),
        "row_count": card["row_count"],
        "created_at_range": card["created_at_range"],
        "cleaning": stats,
    }
    config.SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

    print(json.dumps(snapshot, indent=2))
    print(f"\nSchema card: {config.SCHEMA_CARD_MD}")


if __name__ == "__main__":
    main()
