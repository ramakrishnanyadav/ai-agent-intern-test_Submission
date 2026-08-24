"""
Data Contracts and Type Definitions for Aster & Row Support Agent.
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


class Status(Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    DRAFT = "draft"


class Authority(Enum):
    OFFICIAL_POLICY = "official_policy"
    OFFICIAL_PRODUCT = "official_product"
    SUPPORT_GUIDANCE = "support_guidance"
    INTERNAL = "internal"


class Visibility(Enum):
    CUSTOMER = "customer"
    INTERNAL = "internal"


@dataclass
class DocumentChunk:
    chunk_id: str
    text: str
    filename: str
    title: str
    heading: str
    document_id: str
    status: Status
    authority: Authority
    visibility: Visibility
    effective_date: Optional[str]
    category: str

    @property
    def is_customer_citable(self) -> bool:
        return (
            self.visibility == Visibility.CUSTOMER
            and self.status == Status.ACTIVE
            and self.authority != Authority.INTERNAL
        )


@dataclass
class RetrievalResult:
    chunk: DocumentChunk
    similarity: float


@dataclass
class OrderItem:
    name: str
    quantity: int
    final_sale: bool


@dataclass
class SafeOrderResult:
    order_id: str
    status: str
    items: List[OrderItem]
    placed_at: Optional[str]
    delivered_at: Optional[str]
    carrier: Optional[str]
    tracking_number: Optional[str]
    delivery_estimate: Optional[str]  # strictly None if status in ('cancelled', 'returned')
    customer_safe_message: Optional[str]


@dataclass
class ConversationTurn:
    user_message: str
    assistant_message: str
    topic: Optional[str] = None
    entity: Optional[str] = None
    region: Optional[str] = None
    order_id: Optional[str] = None


@dataclass
class SessionState:
    session_id: str
    last_order_id: Optional[str] = None
    last_topic: Optional[str] = None
    last_entity: Optional[str] = None
    last_region: Optional[str] = None
    history: List[ConversationTurn] = field(default_factory=list)


class ResponseStatus(Enum):
    ANSWERED = "ANSWERED"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    INVALID_ORDER_ID = "INVALID_ORDER_ID"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    CONFLICT = "CONFLICT"
    UNSUPPORTED_ACTION = "UNSUPPORTED_ACTION"
    REFUSED = "REFUSED"
    ERROR = "ERROR"


class HandoffReason(Enum):
    CONFLICT = "CONFLICT"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    UNSUPPORTED_ACTION = "UNSUPPORTED_ACTION"
    SYSTEM_ERROR = "SYSTEM_ERROR"
    PRIVACY_REFUSAL = "PRIVACY_REFUSAL"
    UNKNOWN_ORDER = "UNKNOWN_ORDER"
    INVALID_ORDER_ID = "INVALID_ORDER_ID"
    ORDER_EXCEPTION = "ORDER_EXCEPTION"
    HUMAN_REQUEST = "HUMAN_REQUEST"


@dataclass
class AgentResponse:
    text: str
    sources: List[str]  # e.g., ["01-returns-policy-current.md"]
    status: ResponseStatus
    handoff_reason: Optional[HandoffReason] = None
    tool_calls: List[str] = field(default_factory=list)


@dataclass
class PolicyFact:
    subject: str                  # e.g., "dishwasher"
    product: str                  # e.g., "Breeze Tumbler"
    component: Optional[str]      # e.g., "body" vs "lid"
    condition: str                # e.g., "dishwasher_safe"
    value: Any                    # e.g., False
    scope: str                    # e.g., "hand_wash_only"
    source_filename: str = ""
    source_heading: str = ""


@dataclass
class TraceEvent:
    turn_id: str
    session_id: str
    timestamp: str
    user_message: str
    rewritten_query: Optional[str]
    retrieved_chunk_ids: List[str]
    top_score: float
    tool_name: Optional[str]
    tool_success: bool
    response_status: str
    handoff_reason: Optional[str]
    retrieval_ms: float
    llm_ms: float
    total_ms: float
    conflict_detected: bool
    abstained: bool
    error: Optional[str] = None
