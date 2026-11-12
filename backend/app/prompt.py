import json

from app.llm import RepairContext

_INSTRUCTIONS = """\
You answer questions about a table of city service requests by writing one DuckDB SQL query and choosing how to chart its result.

Reply with exactly these eight fields:
- sql: one read-only SELECT statement (a WITH clause is fine) on the table requests_311. Null only when cannot_answer is set.
- chart_type: one of line, bar, grouped_bar, table, number.
  line: a trend over time; x is a date or a YYYY-MM period.
  bar: one number per category.
  grouped_bar: one number per category and series.
  number: a single value.
  table: anything else.
- x: the result column for the x axis, or null.
- y: the numeric result column to plot, or null.
- series: the result column that splits a grouped_bar into groups, or null.
- title: a short chart title.
- explanation: one sentence on what the query counts or filters.
- cannot_answer: null, or the reason the data cannot answer the question (for example the question asks about something outside the table, or about dates before the data starts). When you set it, sql must be null.

Set exactly one of sql and cannot_answer. Every column named in x, y and series must be a column the query returns, so alias computed columns. Give ORDER BY to results whose order matters.
"""

_EXAMPLES = [
    (
        "What share of requests are marked as duplicates?",
        {
            "sql": "SELECT round(100.0 * count(*) FILTER (WHERE duplicate_request) / count(*), 1) AS duplicate_pct FROM requests_311",
            "chart_type": "number",
            "x": None,
            "y": "duplicate_pct",
            "series": None,
            "title": "Percent of requests marked as duplicates",
            "explanation": "Divides the requests flagged as duplicates by all requests.",
            "cannot_answer": None,
        },
    ),
    (
        "How many requests are still open in each police district?",
        {
            "sql": "SELECT policedistrict, count(*) AS open_requests FROM requests_311 WHERE closed_at IS NULL AND duplicate_request IS NOT TRUE GROUP BY policedistrict ORDER BY open_requests DESC",
            "chart_type": "bar",
            "x": "policedistrict",
            "y": "open_requests",
            "series": None,
            "title": "Open requests by police district",
            "explanation": "Counts non-duplicate requests with no closing date, per police district.",
            "cannot_answer": None,
        },
    ),
    (
        "How many replacement tote requests came in each week of the last 12 weeks?",
        {
            "sql": "SELECT date_trunc('week', created_at)::DATE AS week, count(*) AS requests FROM requests_311 WHERE request_type = 'Replacement Garbage Totes Request' AND duplicate_request IS NOT TRUE AND created_at >= (SELECT max(created_at) FROM requests_311) - INTERVAL 12 WEEK GROUP BY 1 ORDER BY 1",
            "chart_type": "line",
            "x": "week",
            "y": "requests",
            "series": None,
            "title": "Replacement tote requests per week",
            "explanation": "Counts non-duplicate 'Replacement Garbage Totes Request' requests per week over the 12 weeks before the newest record.",
            "cannot_answer": None,
        },
    ),
    (
        "How many 311 requests were filed in 2019?",
        {
            "sql": None,
            "chart_type": "table",
            "x": None,
            "y": None,
            "series": None,
            "title": "Requests filed in 2019",
            "explanation": "The data does not cover 2019.",
            "cannot_answer": "The data starts in May 2024, so there are no requests from 2019 to count.",
        },
    ),
]


def example_answers() -> list[tuple[str, dict]]:
    return list(_EXAMPLES)


def build_system_prompt(schema_card: str) -> str:
    parts = [_INSTRUCTIONS, "Table description:\n", schema_card, "\nExamples:\n"]
    for question, answer in _EXAMPLES:
        parts.append(f"Question: {question}\nAnswer: {json.dumps(answer)}\n")
    return "\n".join(parts)


def build_user_message(question: str, repair_context: RepairContext | None = None) -> str:
    if repair_context is None:
        return question
    return (
        f"{question}\n\n"
        "Your previous query did not work.\n"
        f"Previous SQL:\n{repair_context.previous_sql}\n\n"
        f"Error:\n{repair_context.error}\n\n"
        "Write a corrected answer."
    )
