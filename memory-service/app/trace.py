from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class TraceEvent:
    event_type: str
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    session_id: str = ""
    agent_id: str = "recallops-api"
    model: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    context_tokens: int | None = None
    request_bytes: int = 0
    response_bytes: int = 0
    tool_name: str = ""
    tool_latency_ms: float | None = None
    tool_output_bytes: int = 0
    tool_output_tokens: int = 0
    success: bool = True
    error_type: str = ""
    retry_count: int = 0
    start_time: str = field(default_factory=now)
    end_time: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class TraceRecorder:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path("traces/events.jsonl")
        self._lock = threading.Lock()

    def record(self, event: TraceEvent) -> None:
        event.end_time = event.end_time or now()
        line = json.dumps(asdict(event), ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(line + "\n")


recorder = TraceRecorder()
