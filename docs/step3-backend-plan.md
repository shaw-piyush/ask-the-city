# Step 3: backend plan and task list

Status: approved design, ready to queue. Each task below is one PR. Do them in order; each depends on the ones before it.

Source of truth for product decisions: [DESIGN.md](../DESIGN.md). This file covers only the backend.

## Design

### Request flow

```
POST /ask {question}
  -> validate input (length, empty)
  -> rate limit + daily cap
  -> cache lookup (normalized question)
  -> LLM: question + schema card -> {sql, chart, cannot_answer}
  -> SQL guard (parse, allow-list)          -- on rejection: one repair call
  -> execute on read-only DuckDB (timeout, row cap)  -- on error: one repair call
  -> validate chart spec against result columns, fall back if invalid
  -> response {sql, chart, columns, rows, ...}
```

At most 2 LLM calls per question (first attempt + one repair).

### API contract

`POST /ask`

Request: `{"question": "string, 1-300 chars"}`

Response 200:

```json
{
  "question": "Which council districts have the most pothole requests?",
  "sql": "SELECT council_district, count(*) AS requests FROM requests_311 WHERE ...",
  "chart": {"type": "bar", "x": "council_district", "y": "requests", "series": null, "title": "Pothole requests by council district"},
  "columns": ["council_district", "requests"],
  "rows": [["LOVEJOY", 1234], ["FILLMORE", 1100]],
  "row_count": 9,
  "truncated": false,
  "explanation": "Counts non-duplicate 'Pothole Issue' requests per district.",
  "as_of": "2026-10-28",
  "cached": false,
  "timing_ms": {"llm": 1800, "query": 12}
}
```

Errors (all return `{"error": code, "message": human-readable}`):

| Status | Code | When |
|---|---|---|
| 400 | `invalid_question` | empty, over 300 chars |
| 422 | `cannot_answer` | model says the data can't answer it (message = model's reason) |
| 422 | `unsafe_sql` | guard rejected the SQL twice |
| 422 | `query_failed` | SQL failed twice |
| 429 | `rate_limited` | per-IP limit hit |
| 503 | `daily_cap_reached` | global daily LLM call cap hit; demo buttons still work |
| 503 | `llm_unavailable` | no API key configured, or provider error/timeout |

`GET /health` returns `{"status": "ok"}` with no DB or LLM call (used to wake the free-tier host).

`GET /meta` returns snapshot info (`as_of`, `row_count`, `created_at_range`, `source_url`) from `data/snapshot.json`.

### LLM output schema

The model must return exactly this structure (via tool use / JSON schema, not free text):

```json
{
  "sql": "string or null",
  "chart_type": "line | bar | grouped_bar | table | number",
  "x": "column name or null",
  "y": "column name or null",
  "series": "column name or null (grouped_bar / multi-line only)",
  "title": "short chart title",
  "explanation": "one sentence on what the query counts or filters",
  "cannot_answer": "null, or the reason the data can't answer this"
}
```

### SQL guard rules

Implemented with `sqlglot` (dialect `duckdb`). Reject unless all hold:

1. Parses without error, exactly one statement.
2. Top-level statement is a `SELECT` (CTEs via `WITH` allowed).
3. Every table reference is `requests_311` or a CTE defined in the same query.
4. No table functions or file readers anywhere (`read_csv*`, `read_json*`, `read_parquet`, `read_ndjson*`, `glob`, `query`, `query_table`, any function used in a `FROM` clause).
5. No `PRAGMA`, `SET`, `ATTACH`, `DETACH`, `COPY`, `EXPORT`, `INSTALL`, `LOAD`, `CREATE`, `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CALL`.
6. Row cap: the executor wraps the query as `SELECT * FROM (<sql>) LIMIT 501` and reports `truncated` if 501 rows return (500 shown).

Defense in depth (the guard is not the only layer):
- DuckDB opened `read_only=True`.
- On connect: `SET enable_external_access = false`, then `SET lock_configuration = true`.
- Query timeout of 5 seconds (interrupt the connection from a timer thread).

### Chart validation

- `x`, `y`, `series` must be columns in the result; otherwise fall back.
- `line` requires an x column that is a date/timestamp or ordered period string (`YYYY-MM`); otherwise fall back to `bar`.
- `number` requires exactly one row and one numeric column.
- Fallback order: single numeric cell -> `number`; one text + one numeric column -> `bar`; else `table`.
- Bar charts with more than 25 categories are cut to the top 25, with a note.

### Guardrails and cost

| Guardrail | Default (env var) |
|---|---|
| Max question length | 300 chars |
| Per-IP rate limit | 10/minute, 60/day (`RATE_PER_MIN`, `RATE_PER_DAY`) |
| Global LLM calls per day | 500 (`DAILY_LLM_CALL_CAP`) |
| Max output tokens per call | 800 |
| LLM request timeout | 20 s |
| Cache | in-memory LRU, 1,000 entries, key = lowercased, whitespace-collapsed question |
| Hard monthly spend cap | set on the API key's workspace in the Claude Console, not in code |

No API key configured means `/ask` returns `llm_unavailable`; precomputed demos still work. IP addresses are used in memory for rate limiting only and are never logged or stored.

### Config (env vars)

`ANTHROPIC_API_KEY` (optional; tests never use a real key), `LLM_MODEL` (default `claude-haiku-5-5`), `DB_PATH`, `SCHEMA_CARD_PATH`, `SNAPSHOT_PATH`, `ALLOWED_ORIGINS` (CORS; Vercel URL in prod), plus the guardrail vars above.

### Testing rules (all tasks)

- No test makes a network call. The LLM is always a `FakeLLM` in tests.
- Tests use a small fixture DuckDB built in `conftest.py` from hand-written rows with the real column names. They must pass on a fresh clone without `ask_the_city.duckdb`.
- Optional smoke tests against the real database are marked `@pytest.mark.realdb` and skipped when the file is missing.
- `python -m pytest -q` from `backend/` must pass at the end of every task.

### Layout

```
backend/
  app/
    __init__.py
    main.py        FastAPI app, routes, error handlers
    config.py      settings from env vars
    db.py          read-only connection, hardening, executor with timeout and row cap
    guard.py       SQL guard
    llm.py         LLM interface, AnthropicLLM, FakeLLM, output schema
    prompt.py      prompt builder (schema card + rules + examples)
    charts.py      chart spec validation and fallback
    pipeline.py    ask(question) orchestration, repair loop
    limits.py      rate limiter, daily cap, cache
  scripts/
    precompute_demos.py
  tests/           existing data-layer tests + one test file per module
```

## Tasks

### T1. Backend skeleton

- Add `fastapi`, `uvicorn`, `httpx`, `sqlglot`, `anthropic`, `pydantic` to `requirements.txt`, pinned to exact versions.
- `app/config.py`, `app/main.py` with `GET /health` and `GET /meta`.
- `app/db.py`: `connect()` opens the DB read-only and applies the hardening settings.
- `conftest.py`: session fixture that builds a fixture DB (about 30 rows, real column names, covering several types, districts, statuses, duplicates, open and closed requests).

Done when: `/health` and `/meta` tests pass via `httpx`/`TestClient`; a test proves the connection can't read a file (`SELECT * FROM read_csv('...')` fails) and can't change settings.

### T2. SQL guard

- `app/guard.py`: `check_sql(sql: str) -> GuardResult(ok: bool, reason: str | None)`.

Done when tests cover at least:
- allowed: plain select, `WITH` CTE, joins between CTEs, subqueries, window functions, `date_trunc`, `median`
- rejected: two statements, `DROP`, `INSERT`, `PRAGMA`, `SET`, `ATTACH`, `COPY`, `INSTALL`, other table names, `read_csv`/`read_parquet`/`read_json_auto`/`glob` in `FROM`, table function hidden inside a CTE or subquery, comment tricks (`SELECT 1; -- DROP`), unparseable text, empty string.

### T3. Query executor

- `db.run_query(con, sql) -> QueryResult(columns, rows, row_count, truncated, ms)`.
- Wraps with the row cap, enforces the 5-second timeout, converts dates/timestamps/decimals to JSON-safe values.

Done when tests cover: normal result, truncation at 500, timeout (use a deliberately slow query), JSON-safe types.

### T4. Prompt and output schema

- `app/llm.py`: pydantic `LLMAnswer` matching the output schema; `LLM` protocol with `answer(question, schema_card, repair_context=None) -> LLMAnswer`; `FakeLLM` returning scripted answers.
- `app/prompt.py`: builds the system prompt from `schema_card.md` plus 3 worked examples.
- The worked examples must not be any of the 10 demo questions in DESIGN.md (those are eval items).

Done when: tests check the prompt contains the schema card, the rules and the examples, and that malformed model output raises a clear error.

### T5. Anthropic client

- `AnthropicLLM` implementing the protocol: tool use with the `LLMAnswer` JSON schema, max output tokens, request timeout, returns token usage.
- Maps provider errors and timeouts to an `LLMUnavailable` exception.

Done when: tests mock the Anthropic client object (no network) and cover success, a malformed tool response, and a timeout.

### T6. Chart validation

- `app/charts.py`: `validate_chart(answer, result) -> ChartSpec` implementing the rules and fallback order above.

Done when: tests cover each fallback path, the line-chart date check, the `number` case, and the 25-category cut.

### T7. Pipeline and `/ask`

- `app/pipeline.py`: full flow with the single repair attempt on guard rejection or SQL error (the error message goes back to the model as `repair_context`).
- `POST /ask` in `main.py` with input validation and the error table above.

Done when: integration tests with `FakeLLM` + fixture DB cover success, `cannot_answer`, guard rejection then successful repair, two guard rejections (`unsafe_sql`), SQL error then repair, and `invalid_question`.

### T8. Guardrails

- `app/limits.py`: per-IP sliding-window limiter, global daily LLM call counter (resets at midnight America/New_York), LRU cache.
- Wire into `/ask`: cache before the LLM, limits before the LLM; cache hits don't count against the daily cap.
- Structured log line per request: question, SQL, outcome, timings, token usage. No IPs.

Done when: tests cover rate limiting (429), daily cap (503), cache hit returns `cached: true` without calling the LLM, and no API key gives `llm_unavailable`.

### T9. Demo precompute script

- `scripts/precompute_demos.py`: runs the 10 DESIGN.md demo questions through the pipeline and writes `frontend/public/demos.json` (same shape as the `/ask` response).
- Fails loudly if any demo question errors.

Done when: a test runs the script with `FakeLLM` and the fixture DB. Running it for real needs the API key and the real database, so it is a manual step.

## Not in step 3

Frontend (step 4), eval harness and the 50-question set (step 5), deployment config (step 6).
