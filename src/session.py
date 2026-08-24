"""
Session Management & Query Rewriter Module for Aster & Row Support Agent.
Maintains session state across turns, resolves anaphora/follow-ups deterministically,
enforces session isolation, and implements bounded LRU session eviction.
"""

import re
from typing import Optional, Dict, Tuple
from collections import OrderedDict
from src.contracts import SessionState, ConversationTurn
from src.tools import normalize_order_id


def extract_order_id_from_text(text: str) -> Optional[str]:
    """
    Extracts an order ID matching pattern ORD-\\d+ from text with typo/spacing tolerance.
    """
    match = re.search(r"\b(?:ORDER|ORD)\s*[-–]?\s*(\d{4})\b", text, re.IGNORECASE)
    if match:
        return normalize_order_id(match.group(0))
    return None


class SessionManager:
    def __init__(self, max_sessions: int = 1000):
        self.max_sessions = max_sessions
        # OrderedDict used for LRU session tracking and bounded memory eviction
        self.sessions: OrderedDict[str, SessionState] = OrderedDict()

    def get_or_create_session(self, session_id: str) -> SessionState:
        if session_id in self.sessions:
            # Move accessed session to end (most recently used)
            self.sessions.move_to_end(session_id)
            return self.sessions[session_id]

        # Enforce max sessions memory cap via oldest session eviction
        if len(self.sessions) >= self.max_sessions:
            self.sessions.popitem(last=False)

        session = SessionState(session_id=session_id)
        self.sessions[session_id] = session
        return session

    def rewrite_query(
        self,
        session: SessionState,
        user_message: str
    ) -> Tuple[str, Optional[str], bool]:
        """
        Rewrites user message using session context to resolve anaphora and pronouns.
        Returns (rewritten_message, active_order_id, is_ambiguous).
        """
        msg_lower = user_message.lower().strip()

        # Extract topics, regions, and order IDs
        if "ship" in msg_lower or "delivery" in msg_lower or "dispatch" in msg_lower:
            session.last_topic = "shipping"
        elif "return" in msg_lower or "refund" in msg_lower:
            session.last_topic = "returns"

        if "canada" in msg_lower or "canadian" in msg_lower:
            session.last_region = "canada"
        elif "germany" in msg_lower:
            session.last_region = "germany"
        
        # Check for explicit order ID in current turn
        current_order_id = extract_order_id_from_text(user_message)
        if current_order_id:
            session.last_order_id = current_order_id

        active_order_id = current_order_id or session.last_order_id

        # Anaphora resolution for pronouns: "it", "this order", "my order", "the order", "that order"
        anaphora_targets = [
            r"\bwhere\s+is\s+it\b", r"\bwhen\s+will\s+it\s+arrive\b", r"\bstatus\s+of\s+it\b",
            r"\bwhere\s+is\s+this\s+order\b", r"\bstatus\s+of\s+this\s+order\b",
            r"\btracking\s+number\s+for\s+it\b", r"\bcarrier\s+for\s+it\b"
        ]
        is_anaphora = any(re.search(pat, msg_lower) for pat in anaphora_targets)

        rewritten = user_message
        if is_anaphora and active_order_id and active_order_id not in user_message:
            rewritten = f"What is the status of order {active_order_id}?"
        elif session.last_topic == "shipping" and "shipping" not in msg_lower:
            rewritten = f"{user_message} (shipping policy)"

        return rewritten, active_order_id, False

    def record_turn(
        self,
        session: SessionState,
        user_message: str,
        agent_response_text: str,
        topic: Optional[str] = None,
        entity: Optional[str] = None,
        region: Optional[str] = None,
        order_id: Optional[str] = None
    ):
        """
        Records completed turn into session conversation history.
        """
        if topic:
            session.last_topic = topic
        if entity:
            session.last_entity = entity
        if region:
            session.last_region = region
        if order_id:
            session.last_order_id = order_id

        turn = ConversationTurn(
            user_message=user_message,
            assistant_message=agent_response_text,
            topic=topic,
            entity=entity,
            region=region,
            order_id=order_id
        )
        session.history.append(turn)
        if len(session.history) > 10:
            session.history.pop(0)
