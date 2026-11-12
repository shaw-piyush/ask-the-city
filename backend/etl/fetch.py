"""Download Buffalo 311 metadata and rows from the Socrata API.

Usage (from backend/):
    python -m etl.fetch --metadata-only   # print the real column list, download nothing else
    python -m etl.fetch                   # metadata + all rows -> data/raw/requests.jsonl
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

from . import config

RETRYABLE = {429, 500, 502, 503, 504}


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = "ask-the-city/0.1 (student portfolio project)"
    token = os.getenv("SOCRATA_APP_TOKEN")  # optional; raises Socrata's rate limits
    if token:
        s.headers["X-App-Token"] = token
    return s


def get_json(session: requests.Session, url: str, params: dict | None = None, attempts: int = 4):
    for attempt in range(1, attempts + 1):
        try:
            resp = session.get(url, params=params, timeout=90)
            if resp.status_code in RETRYABLE:
                raise requests.HTTPError(f"HTTP {resp.status_code}")
            resp.raise_for_status()
            return resp.json()
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as exc:
            if attempt == attempts:
                raise RuntimeError(f"GET {url} failed after {attempts} attempts: {exc}") from exc
            wait = 2 ** attempt
            print(f"  retry {attempt}/{attempts - 1} in {wait}s ({exc})", file=sys.stderr)
            time.sleep(wait)


def fetch_metadata(session: requests.Session) -> dict:
    url = f"{config.DOMAIN}/api/views/{config.DATASET_ID}.json"
    meta = get_json(session, url)
    columns = [
        {
            "field": c["fieldName"],
            "name": c.get("name", ""),
            "type": c.get("dataTypeName", "text"),
            "description": (c.get("description") or "").strip(),
        }
        for c in meta.get("columns", [])
        if not c["fieldName"].startswith(":")  # skip Socrata system columns
    ]
    return {
        "dataset_id": config.DATASET_ID,
        "dataset_url": f"{config.DOMAIN}/d/{config.DATASET_ID}",
        "name": meta.get("name"),
        "license": (meta.get("license") or {}).get("name") or meta.get("licenseId"),
        "rows_updated_at": meta.get("rowsUpdatedAt"),  # unix seconds
        "columns": columns,
    }


def fetch_rows(session: requests.Session, out_path: Path) -> int:
    """Page through the dataset in stable :id order and write newline-delimited JSON."""
    url = f"{config.DOMAIN}/resource/{config.DATASET_ID}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".jsonl.part")
    total = 0
    with tmp.open("w", encoding="utf-8") as f:
        while True:
            params = {"$limit": config.PAGE_SIZE, "$offset": total, "$order": ":id"}
            page = get_json(session, url, params)
            for row in page:
                f.write(json.dumps(row) + "\n")
            total += len(page)
            print(f"  fetched {total:,} rows")
            if len(page) < config.PAGE_SIZE:
                break
    if total == 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("API returned zero rows; refusing to overwrite the existing snapshot")
    tmp.replace(out_path)  # atomic swap: a failed run never leaves a half-written file
    return total


def print_columns(meta: dict) -> None:
    print(f"\n{meta['name']}  ({meta['dataset_url']})  license: {meta['license']}\n")
    print(f"{'field':<28}{'type':<16}description")
    for c in meta["columns"]:
        print(f"{c['field']:<28}{c['type']:<16}{c['description'][:70]}")
    print(f"\n{len(meta['columns'])} columns")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--metadata-only", action="store_true")
    args = parser.parse_args()

    session = make_session()
    meta = fetch_metadata(session)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.METADATA_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print_columns(meta)
    if args.metadata_only:
        return
    n = fetch_rows(session, config.RAW_DIR / "requests.jsonl")
    print(f"\nWrote {n:,} rows to {config.RAW_DIR / 'requests.jsonl'}")


if __name__ == "__main__":
    main()
