"""
Tool Registry & Capability Router Module for Aster & Row Support Agent.
Enforces tool authorization boundaries and handles unsupported actions safely.
"""

import re
from typing import Optional, Dict, Any
from src.contracts import ResponseStatus, HandoffReason, AgentResponse

class ToolRegistry:
    def __init__(self):
        self.allowed_tools = {
            "lookup_order": {
                "name": "lookup_order",
                "description": "Looks up order status by order ID",
                "required_arg": "order_id"
            }
        }

    def check_unsupported_action_intent(self, user_message: str) -> Optional[AgentResponse]:
        """
        Detects direct action requests (cancel/terminate order, change address, issue refund)
        and responds with clear limitation statement without claiming completion.
        """
        msg_lower = user_message.lower()

        # Catch direct action requests regardless of polite filler words or alternate verbs
        cancellation_patterns = [
            r"\bcancel\w*\b",
            r"\bterminate\w*\b",
            r"\bback\s+out\s+of\b",
            r"\bstop\s+(?:my\s+)?order\b",
            r"\bvoid\s+(?:my\s+)?order\b",
            r"\bwithdraw\s+(?:my\s+)?order\b"
        ]
        address_patterns = [r"\bchange\s+(?:my\s+)?address\b", r"\bupdate\s+(?:my\s+)?address\b"]
        refund_patterns = [r"\bissue\s+(?:a\s+)?refund\b", r"\bprocess\s+(?:a\s+)?refund\b", r"\brefund\s+my\b"]

        if any(re.search(p, msg_lower) for p in cancellation_patterns) and not ("policy" in msg_lower or "how long" in msg_lower or "window" in msg_lower):
            return AgentResponse(
                text="I cannot process cancellations directly through this AI support agent. However, I can explain our cancellation policy or connect you with a human support representative.",
                sources=[],
                status=ResponseStatus.UNSUPPORTED_ACTION,
                handoff_reason=HandoffReason.UNSUPPORTED_ACTION,
                tool_calls=[]
            )

        if any(re.search(p, msg_lower) for p in address_patterns):
            return AgentResponse(
                text="I cannot update or change shipping addresses directly through this support agent. However, I can explain our address change policy or connect you with human support.",
                sources=[],
                status=ResponseStatus.UNSUPPORTED_ACTION,
                handoff_reason=HandoffReason.UNSUPPORTED_ACTION,
                tool_calls=[]
            )

        if any(re.search(p, msg_lower) for p in refund_patterns):
            return AgentResponse(
                text="I cannot issue or process refunds directly through this support agent. However, I can explain our refund policy or connect you with human support.",
                sources=[],
                status=ResponseStatus.UNSUPPORTED_ACTION,
                handoff_reason=HandoffReason.UNSUPPORTED_ACTION,
                tool_calls=[]
            )

        return None
