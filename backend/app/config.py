import os
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BACKEND_DIR / "data"


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str | None = None
    llm_model: str = "claude-haiku-5-5"
    db_path: Path = DATA_DIR / "ask_the_city.duckdb"
    schema_card_path: Path = DATA_DIR / "schema_card.md"
    snapshot_path: Path = DATA_DIR / "snapshot.json"
    allowed_origins: list[str] = field(default_factory=list)
    max_question_chars: int = 300
    max_output_tokens: int = 800
    llm_timeout_s: float = 20.0
    query_timeout_s: float = 5.0

    @classmethod
    def from_env(cls) -> "Settings":
        origins = os.environ.get("ALLOWED_ORIGINS", "")
        return cls(
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
            llm_model=os.environ.get("LLM_MODEL", cls.llm_model),
            db_path=Path(os.environ.get("DB_PATH", DATA_DIR / "ask_the_city.duckdb")),
            schema_card_path=Path(
                os.environ.get("SCHEMA_CARD_PATH", DATA_DIR / "schema_card.md")
            ),
            snapshot_path=Path(
                os.environ.get("SNAPSHOT_PATH", DATA_DIR / "snapshot.json")
            ),
            allowed_origins=[o.strip() for o in origins.split(",") if o.strip()],
        )
