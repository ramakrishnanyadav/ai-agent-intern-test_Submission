"""
Observability & Trace Logger Module for Aster & Row Support Agent.
Logs structured per-turn JSON-lines events with strict allowlisting and input PII scrubbing.
"""

import json
import re
import time
from pathlib import Path
from typing import Optional, Dict, Any
from src.contracts import TraceEvent


def scrub_pii_from_log_text(text: Optional[str]) -> Optional[str]:
    """Scrubs sensitive customer emails, phone numbers, and addresses from trace log text."""
    if not text:
        return text

    # Redact email addresses
    scrubbed = re.sub(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "[EMAIL_REDACTED]", text)
    # Redact phone numbers
    scrubbed = re.sub(r"\b(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}\b", "[PHONE_REDACTED]", scrubbed)
    # Redact street addresses
    scrubbed = re.sub(
        r"\b\d{1,5}\s+[A-Za-z0-9\s.,]+\b(?:Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Drive|Dr|Boulevard|Blvd|Court|Ct)\b",
        "[ADDRESS_REDACTED]",
        scrubbed,
        flags=re.IGNORECASE
    )
    return scrubbed


class TraceLogger:
    def __init__(self, log_path: str = "logs/traces.jsonl"):
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_event(self, event: TraceEvent):
        """Logs sanitized TraceEvent object to JSON-lines file with input PII scrubbing."""
        record = {
            "turn_id": event.turn_id,
            "session_id": event.session_id,
            "timestamp": event.timestamp,
            "user_message": scrub_pii_from_log_text(event.user_message),
            "rewritten_query": scrub_pii_from_log_text(event.rewritten_query),
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
