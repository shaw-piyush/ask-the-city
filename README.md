# Ask-the-city

Ask plain-English questions about Buffalo's 311 service requests and get a chart plus the generated SQL.

Status: backend in progress (step 3 of 6). Data layer, SQL guard, query executor and LLM interface are done. Design decisions are in [DESIGN.md](DESIGN.md).

## Data layer quickstart

Tested on Python 3.13 and 3.14. Dependencies are pinned: a DuckDB file can only be opened by the same or a newer DuckDB version, so the machine that builds the database and the server that reads it must match. From `backend/`:

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m pytest -q                      # unit tests for the cleaning rules
python -m etl.fetch --metadata-only      # print the source's real column list
python -m etl.build                      # fetch, clean, build DuckDB, write schema card
python -m etl.build --skip-fetch         # rebuild from the last download, no network
```

Outputs in `backend/data/`:

| File | What it is |
|---|---|
| `ask_the_city.duckdb` | cleaned `requests_311` table (gitignored) |
| `raw/requests.jsonl` | raw API download (gitignored) |
| `source_metadata.json` | column list and license from Socrata |
| `schema_card.md` / `.json` | the data description the LLM sees |
| `snapshot.json` | "as of" date, row count, cleaning stats |

If the fetch hits repeated HTTP 429 errors, get a free app token from data.buffalony.gov and set `SOCRATA_APP_TOKEN`.

## Data source

[311 Service Requests (May 2024 – Present)](https://data.buffalony.gov/d/3tj7-3tdz), Open Data Buffalo, public domain.
