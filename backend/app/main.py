import json

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="Ask the City")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/meta")
    def meta():
        try:
            snap = json.loads(settings.snapshot_path.read_text())
            created_range = snap["created_at_range"]
            return {
                "as_of": created_range[-1][:10],
                "row_count": snap["row_count"],
                "created_at_range": created_range,
                "source_url": snap["source_url"],
            }
        except (OSError, ValueError, KeyError, IndexError):
            return JSONResponse(
                status_code=503,
                content={"error": "meta_unavailable", "message": "Snapshot info is not available."},
            )

    return app


app = create_app()
