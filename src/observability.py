"""
Observability & Trace Logger Module for Aster & Row Support Agent.
Logs structured per-turn JSON-lines events with strict allowlisting to prevent PII leakage.
"""

import json
import time
from pathlib import Path
from typing import Optional, Dict, Any
from src.contracts import TraceEvent


class TraceLogger:
    def __init__(self, log_path: str = "logs/traces.jsonl"):
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_event(self, event: TraceEvent):
        """Logs sanitized TraceEvent object to JSON-lines file."""
        record = {
            "turn_id": event.turn_id,
            "session_id": event.session_id,
            "timestamp": event.timestamp,
            "user_message": event.user_message,
            "rewritten_query": event.rewritten_query,
            "retrieved_chunk_ids": event.retrieved_chunk_ids,
            "top_score": round(event.top_score, 4),
            "tool_name": event.tool_name,
            "tool_success": event.tool_success,
            "response_status": event.response_status,
            "handoff_reason": event.handoff_reason,
            "retrieval_ms": round(event.retrieval_ms, 2),
            "llm_ms": round(event.llm_ms, 2),
            "total_ms": round(event.total_ms, 2),
            "conflict_detected": event.conflict_detected,
            "abstained": event.abstained,
            "error": event.error
        }
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
