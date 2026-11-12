"""Shared paths and constants for the data layer."""
import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.getenv("ATC_DATA_DIR", BACKEND_DIR / "data"))

RAW_DIR = DATA_DIR / "raw"
METADATA_PATH = DATA_DIR / "source_metadata.json"
DB_PATH = DATA_DIR / "ask_the_city.duckdb"
SNAPSHOT_PATH = DATA_DIR / "snapshot.json"
SCHEMA_CARD_JSON = DATA_DIR / "schema_card.json"
SCHEMA_CARD_MD = DATA_DIR / "schema_card.md"

TABLE = "requests_311"

DOMAIN = "https://data.buffalony.gov"
DATASET_ID = "3tj7-3tdz"  # 311 Service Requests (May 2024 - Present), public domain
PAGE_SIZE = 50_000

# Generous bounding box around the City of Buffalo; points outside are nulled.
LAT_RANGE = (42.75, 43.05)
LON_RANGE = (-79.00, -78.70)
