from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

ALLOWED_TABLE = "requests_311"
FORBIDDEN_FUNCTIONS = {
    "current_setting",
    "getenv",
    "query",
    "query_table",
    "which_secret",
    "version",
    "current_version",
}
FORBIDDEN_FUNCTION_PREFIXES = ("read_", "glob", "duckdb_", "pragma_")

_FORBIDDEN_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.Command,
    exp.Copy,
    exp.Set,
    exp.Pragma,
    exp.Attach,
    exp.Detach,
    exp.Use,
    exp.Merge,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
)


@dataclass(frozen=True)
class GuardResult:
    ok: bool
    reason: str | None = None


def _reject(reason: str) -> GuardResult:
    return GuardResult(ok=False, reason=reason)


def check_sql(sql: str) -> GuardResult:
    """Accept only a single read-only SELECT over requests_311 (or its own CTEs)."""
    if not isinstance(sql, str) or not sql.strip():
        return _reject("The query is empty.")
    try:
        statements = [s for s in sqlglot.parse(sql, read="duckdb") if s is not None]
    except SqlglotError as e:
        return _reject(f"The query could not be parsed: {str(e).splitlines()[0][:150]}")
    except Exception:
        return _reject("The query could not be parsed.")
    if len(statements) != 1:
        return _reject("Exactly one SQL statement is allowed.")
    tree = statements[0]
    if not isinstance(tree, (exp.Select, exp.SetOperation)):
        return _reject("Only a SELECT query is allowed.")

    for node in tree.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            return _reject(f"{type(node).__name__.upper()} statements are not allowed.")
        if isinstance(node, (exp.Func, exp.Anonymous)) and not isinstance(node, exp.Table):
            name = (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).lower()
            if isinstance(node, exp.CurrentVersion):
                name = "version"
            if name in FORBIDDEN_FUNCTIONS or name.startswith(FORBIDDEN_FUNCTION_PREFIXES):
                return _reject(f"The function {name} is not allowed.")

    cte_names = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            return _reject("Table functions and file readers are not allowed in FROM.")
        if table.args.get("db") or table.args.get("catalog"):
            return _reject("Schema-qualified table names are not allowed; use requests_311.")
        name = table.name.lower()
        if name != ALLOWED_TABLE and name not in cte_names:
            return _reject(f"Table {table.name} is not allowed; only requests_311 can be queried.")
    for node in tree.find_all(exp.Subquery, exp.From, exp.Join):
        target = node.this
        if isinstance(target, (exp.Func, exp.Anonymous, exp.Unnest, exp.Values)) or (
            isinstance(target, exp.Table) and not isinstance(target.this, exp.Identifier)
        ):
            return _reject("Table functions and file readers are not allowed in FROM.")
    return GuardResult(ok=True)
