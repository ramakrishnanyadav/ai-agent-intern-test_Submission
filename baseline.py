"""
Naive Baseline RAG Agent Implementation.
Used to measure real baseline evaluation performance prior to reliability engineering.
- No metadata front-matter filtering (uses superseded and draft documents).
- No PII scrubbing or field allowlisting on order lookups.
- No status precedence enforcement (returns stale ETAs on cancelled orders).
- No deterministic conflict detection or query rewriting.
"""

import json
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
from src.contracts import AgentResponse, ResponseStatus, HandoffReason


class NaiveBaselineAgent:
    def __init__(self, kb_dir: str = "knowledge-base", data_path: str = "data/orders.json"):
        self.kb_dir = Path(kb_dir)
        self.data_path = Path(data_path)
        self.docs: List[Dict[str, str]] = []
        self.orders: Dict[str, Dict[str, Any]] = {}
        self._load_docs()
        self._load_orders()

    def _load_docs(self):
        for fpath in sorted(self.kb_dir.glob("*.md")):
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            self.docs.append({"filename": fpath.name, "text": content})

    def _load_orders(self):
        if self.data_path.exists():
            with open(self.data_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for rec in data.get("orders", []):
                oid = rec.get("order_id")
                if oid:
                    self.orders[oid.upper()] = rec

    def process_message(self, user_message: str, session_id: str = "default_session") -> AgentResponse:
        msg_lower = user_message.lower()

        # Naive order lookup (returns raw un-sanitized fields)
        match = re.search(r"\bORD-\d+\b", user_message, re.IGNORECASE)
        if match or "order" in msg_lower:
            if match:
                oid = match.group(0).upper()
                if oid in self.orders:
                    rec = self.orders[oid]
                    # Naive baseline returns raw dict representation including stale ETA and PII
                    return AgentResponse(
                        text=f"Order Details for {oid}: Status={rec.get('status')}, ETA={rec.get('estimated_delivery')}, Customer={rec.get('customer')}, Internal={rec.get('internal')}",
                        sources=[],
                        status=ResponseStatus.ANSWERED,
                        tool_calls=[f"lookup_order('{oid}')"]
                    )
                else:
                    return AgentResponse(
                        text=f"Order {oid} status is processing.",
                        sources=[],
                        status=ResponseStatus.ANSWERED,
                        tool_calls=[f"lookup_order('{oid}')"]
                    )

        # Naive keyword matching without front-matter metadata filtering
        best_doc = None
        best_score = 0

        query_words = set(re.findall(r"\w+", msg_lower))
        for doc in self.docs:
            doc_words = set(re.findall(r"\w+", doc["text"].lower()))
            score = len(query_words.intersection(doc_words))
            if score > best_score:
                best_score = score
                best_doc = doc

        if best_doc and best_score > 0:
            # Naive baseline cites whatever document scored highest, including superseded or internal docs
            return AgentResponse(
                text=f"{best_doc['text'][:250]} [{best_doc['filename']}]",
                sources=[best_doc["filename"]],
                status=ResponseStatus.ANSWERED
            )

        return AgentResponse(
            text="I'm sorry, I don't know the answer.",
            sources=[],
            status=ResponseStatus.INSUFFICIENT_EVIDENCE
        )


def run_baseline_evaluation():
    from eval import EXTENDED_CASES, evaluate_case
    with open("evaluation/visible-cases.json", "r", encoding="utf-8") as f:
        visible_cases = json.load(f).get("cases", [])
    
    all_cases = visible_cases + EXTENDED_CASES
    baseline = NaiveBaselineAgent()

    passed_count = 0
    cat_summary: Dict[str, Dict[str, int]] = {}

    for case in all_cases:
        passed, _ = evaluate_case(baseline, case)
        cat = case.get("category", "general")
        cat_summary.setdefault(cat, {"passed": 0, "total": 0})
        cat_summary[cat]["total"] += 1
        if passed:
            passed_count += 1
            cat_summary[cat]["passed"] += 1

    print("=======================================================")
    print("NAIVE BASELINE EVALUATION RUN (REAL MEASURED RESULTS)")
    print("=======================================================")
    for cat, counts in cat_summary.items():
        pct = (counts["passed"] / counts["total"]) * 100
        print(f"  {cat:<25}: {counts['passed']}/{counts['total']} ({pct:.1f}%)")

    overall = (passed_count / len(all_cases)) * 100
    print("-------------------------------------------------------")
    print(f"  BASELINE OVERALL SCORE      : {passed_count}/{len(all_cases)} ({overall:.1f}%)")
    print("=======================================================\n")
    return overall, cat_summary


if __name__ == "__main__":
    run_baseline_evaluation()
