"""Entry point: python run.py  ->  POST http://localhost:8000/run"""
import os

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

load_dotenv()
from app.agents import run_agent  # noqa: E402  (after load_dotenv so env is set)

app = FastAPI(title="Why Agent")


class RunRequest(BaseModel):
    request_id: str | None = None
    user_query: str
    context: dict | None = None


@app.post("/run")
def run(req: RunRequest):
    try:
        return run_agent(req.model_dump())
    except Exception as e:  # structured error instead of a stack trace
        return JSONResponse(status_code=502, content={"request_id": req.request_id, "status": "error",
                                                     "error": type(e).__name__, "detail": str(e)})


@app.get("/health")
def health():
    return {"status": "ok", "sample_mode": os.getenv("SAMPLE_MODE", "false")}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
