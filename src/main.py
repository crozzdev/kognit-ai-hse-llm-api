from fastapi import FastAPI
from mangum import Mangum

try:
    import config  # Local dev
except ImportError:
    from src import config  # AWS Lambda

app = FastAPI(title="Kognit AI HSE LLM API", root_path="/llm")


@app.get("/")
def read_root():
    return {"Hello": "LLM API from GitHub Actions!"}


@app.get("/items/{item_id}")
def read_item(item_id: int, q: str | None = None):
    return {"item_id": item_id, "q": q}


# ── Health Check Endpoint ─────────────────────────────────────────────────────
@app.get("/health")
def health_check():
    """Health check endpoint for AWS Lambda and postgres connectivity."""
    pg_status = config.check_postgres()
    # TO-DO: Health check for OpeanAI API connectivity can be added here in the future
    all_ok = pg_status["status"] == "ok"
    return {
        "postgres": pg_status,
        "overall": {
            "status": "ok" if all_ok else "failed",
            "message": "✅ All connections healthy"
            if all_ok
            else "❌ One or more connections failed",
        },
    }


handler = Mangum(app, api_gateway_base_path="/llm")
