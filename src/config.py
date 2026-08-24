"""
Centralized Configuration Settings Module for Aster & Row Support Agent.
Extracts system magic numbers, retrieval thresholds, timeouts, and model parameters.
"""

import os
from dataclasses import dataclass


@dataclass
class AgentConfig:
    # LLM Settings (Updated to active gemini-2.0-flash model)
    llm_model: str = os.environ.get("LLM_MODEL", "gemini/gemini-2.0-flash")
    llm_timeout_seconds: float = 3.0
    llm_num_retries: int = 0

    # Retrieval Settings
    bm25_k1: float = 1.5
    bm25_b: float = 0.75
    top_k_chunks: int = 4
    min_similarity_threshold: float = 0.20

    # Session & History Settings
    max_history_turns: int = 10

    # File Paths
    kb_dir: str = "knowledge-base"
    data_path: str = "data/orders.json"
    log_path: str = "logs/traces.jsonl"


# Global singleton instance
config = AgentConfig()
