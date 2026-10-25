"""JSONL trace logging: every agent action goes to logs/<trace_id>.jsonl and stdout."""
import json
import os
import time
import uuid
from datetime import datetime, timezone

LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")


class Tracer:
    def __init__(self, trace_id: str | None = None):
        self.trace_id = trace_id or f"trace-{time.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}"
        os.makedirs(LOG_DIR, exist_ok=True)
        self.path = os.path.join(LOG_DIR, f"{self.trace_id}.jsonl")

    def log(self, agent_name: str, action: str, input_summary: str = "", output_summary: str = "",
            target_agent: str | None = None, model: str | None = None, confidence: float | None = None,
            retry_count: int = 0, status: str = "success") -> None:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "trace_id": self.trace_id, "agent_name": agent_name, "action": action,
            "input_summary": input_summary[:300], "output_summary": output_summary[:300],
            "target_agent": target_agent, "model": model, "confidence": confidence,
            "retry_count": retry_count, "status": status,
        }
        line = json.dumps(event)
        print(line, flush=True)
        with open(self.path, "a") as f:
            f.write(line + "\n")
