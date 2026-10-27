"""Entry point: python run.py  ->  POST http://localhost:8000/run"""
from __future__ import annotations
import os

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from typing import Optional

from pydantic import BaseModel, Field

load_dotenv()
from app.casefile import CASE_DIR  # noqa: E402  (after load_dotenv so env is set)
from app.ringbreaker import data_layer, run_ring  # noqa: E402

app = FastAPI(title="Ringbreaker")


class RunRequest(BaseModel):
    request_id: Optional[str] = Field(None, max_length=100)
    user_query: str = Field(..., min_length=1, max_length=2000, pattern=r"\S")  # no empty, blank or huge queries reach the model
    context: Optional[dict] = None


@app.post("/run")
def run(req: RunRequest):
    try:
        return run_ring(req.model_dump())
    except Exception as e:  # structured error instead of a stack trace
        return JSONResponse(status_code=502, content={"request_id": req.request_id, "status": "error",
                                                     "error": type(e).__name__, "detail": str(e)})


@app.get("/case/{trace_id}")
def case(trace_id: str):
    path = os.path.join(CASE_DIR, os.path.basename(trace_id) + ".html")  # basename blocks path traversal
    if not os.path.exists(path):
        return JSONResponse(status_code=404, content={"status": "error", "detail": "no such case"})
    return FileResponse(path, media_type="text/html")


@app.get("/health")
def health():
    return {"status": "ok", "sample_mode": os.getenv("SAMPLE_MODE", "false"), "data_layer": data_layer()}


if __name__ == "__main__":
    # localhost-only by default (no auth on /run); the Dockerfile sets HOST=0.0.0.0
    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")))
