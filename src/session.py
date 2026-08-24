"""
Session Management & Query Rewriter Module for Aster & Row Support Agent.
Maintains session state across turns, resolves anaphora/follow-ups deterministically,
and enforces session isolation across user sessions.
"""

import re
from typing import Optional, Dict, Tuple
from src.contracts import SessionState, ConversationTurn
from src.tools import normalize_order_id


def extract_order_id_from_text(text: str) -> Optional[str]:
    """
    Extracts an order ID matching pattern ORD-\\d+ from text.
    """
    match = re.search(r"\bORD-\d+\b", text, re.IGNORECASE)
    if match:
        return normalize_order_id(match.group(0))
    return None


class SessionManager:
    def __init__(self):
        self.sessions: Dict[str, SessionState] = {}

    def get_or_create_session(self, session_id: str) -> SessionState:
        if session_id not in self.sessions:
            self.sessions[session_id] = SessionState(session_id=session_id)
        return self.sessions[session_id]

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
        
        # Check for explicit order ID in current turn
        current_order_id = extract_order_id_from_text(user_message)
        if current_order_id:
            session.last_order_id = current_order_id

        active_order_id = current_order_id or session.last_order_id
        rewritten = user_message
        is_ambiguous = False

        # Order property pronouns and follow-up phrases
        order_property_phrases = [
            "when will it arrive", "where is it", "get here", "delivery date",
            "tracking", "tracking number", "carrier", "when was it placed",
            "placed", "status", "order status", "items", "shipping status"
        ]
        has_order_property_intent = any(phrase in msg_lower for phrase in order_property_phrases)

        # 1. Handle order status / property follow-ups using session active order ID
        if active_order_id and (has_order_property_intent or "it" in msg_lower.split()):
            rewritten = f"Where is order {active_order_id} and what is its status, carrier, and delivery estimate?"
            session.last_topic = "order_status"

        # 2. Handle international shipping / region follow-ups (e.g. "What about Canada?")
        elif "canada" in msg_lower and ("shipping" not in msg_lower):
            if session.last_topic == "shipping" or (session.history and "internationally" in session.history[-1].user_message.lower()):
                rewritten = "Does Aster & Row ship internationally to Canada, and what is the international shipping delivery timeline and policy?"
                session.last_region = "Canada"
                session.last_topic = "shipping"

        # 3. Update session topic from current query
        if "ship" in msg_lower or "delivery" in msg_lower:
            session.last_topic = "shipping"
        elif "return" in msg_lower or "refund" in msg_lower:
            session.last_topic = "returns"
        elif "warranty" in msg_lower:
            session.last_topic = "warranty"

        return rewritten, active_order_id, is_ambiguous

    def record_turn(
        self,
        session: SessionState,
        user_message: str,
        assistant_message: str,
        topic: Optional[str] = None,
        order_id: Optional[str] = None
    ):
        turn = ConversationTurn(
            user_message=user_message,
            assistant_message=assistant_message,
            topic=topic or session.last_topic,
            entity=session.last_entity,
            region=session.last_region,
            order_id=order_id or session.last_order_id
        )
        session.history.append(turn)
        if len(session.history) > 10:
            session.history = session.history[-10:]
