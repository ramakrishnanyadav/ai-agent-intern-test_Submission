"""
Response Output Validator Module for Aster & Row Support Agent.
Enforces defense-in-depth safety checks: PII/sensitive data leakage prevention,
untrusted document citation enforcement, and forbidden source filtering.
"""

import re
from typing import List, Tuple, Optional, Union
from src.contracts import AgentResponse, RetrievalResult, ResponseStatus, HandoffReason, Visibility


PII_PATTERNS = [
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",  # Email addresses
    r"\b\d{1,5}\s+[A-Za-z0-9\s.,]+\b(?:Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Drive|Dr|Boulevard|Blvd|Court|Ct)\b",  # Postal street addresses
    r"\brisk\s*score\b",  # Risk score keywords
    r"\brisk\s*rating\b", # Risk rating keywords
    r"\bfraud\s*review\b", # Fraud review keywords
    r"\bfraud\s*(team|notes|dept|department)\b", # Fraud team/notes
    r"\bsecurity\s*(team|notes)\b", # Security team/notes
    r"\binternal\s*note[s]?\b", # Internal notes
    r"\bwarehouse\s*note[s]?\b", # Warehouse notes
    r"\bteam\s*note[s]?\b", # Team notes
    r"\bstaff\s*note[s]?\b", # Staff notes
    r"\bsupport\s*note[s]?\b", # Support notes
    r"\binternal\s*flags?\b", # Internal flags
    r"\border\s*flags?\b", # Order flags
    r"\brecipient\s*name[s]?\b", # Recipient name
    r"\baccount\s*(holder|owner|name)\b", # Account holder/owner
    r"\bwho\s+paid\b", # PII who paid
    r"\bbilling\s+address\b", # Billing address
    r"\bpayment\s+method\s+(used|on\s+file)\b", # Payment method on order
    r"\bcontact\s*info\b" # Customer contact info
]

PROMPT_LEAKAGE_PATTERNS = [
    r"DATA BOUNDARY",
    r"SYSTEM INSTRUCTIONS",
    r"You are Aster & Row",
    r"DO NOT REVEAL",
    r"Here is my prompt",
    r"System Override"
]


def check_pii_leakage(text: str) -> bool:
    """Returns True if text contains prohibited PII or internal security data."""
    text_lower = text.lower()
    for pattern in PII_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return True
    return False


def check_system_prompt_leakage(text: str) -> bool:
    """Returns True if text contains internal prompt instructions or data boundaries."""
    for pattern in PROMPT_LEAKAGE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def validate_citations(
    target: Union[AgentResponse, str],
    retrieved_results: List[RetrievalResult]
) -> Tuple[List[str], bool]:
    """
    Validates that response sources are customer-citable and present in retrieved results.
    Returns (valid_sources, all_citations_ok_boolean).
    """
    retrieved_map = {r.chunk.filename: r.chunk for r in retrieved_results}
    for r in retrieved_results:
        retrieved_map[r.chunk.title] = r.chunk

    sources = target.sources if isinstance(target, AgentResponse) else []
    if isinstance(target, str):
        # Extract cited bracket sources if string passed
        sources = re.findall(r"\[([a-zA-Z0-9\.\-\_\s\—\–]+)\]", target)

    valid_sources = []
    invalid_sources = []

    for src in sources:
        chunk = None
        for k, v in retrieved_map.items():
            if src.lower() in k.lower() or k.lower() in src.lower():
                chunk = v
                break
        if chunk and chunk.is_customer_citable:
            if chunk.filename not in valid_sources:
                valid_sources.append(chunk.filename)
        else:
            invalid_sources.append(src)

    all_ok = len(invalid_sources) == 0
    return list(dict.fromkeys(valid_sources)), all_ok


def validate_response(
    response: AgentResponse,
    retrieved_results: List[RetrievalResult]
) -> AgentResponse:
    """
    Executes output-side safety validation on response candidate.
    Strips invalid citations, blocks PII leakage, and enforces privacy refusal.
    """
    # Deduplicate sources up front
    if response.sources:
        response.sources = list(dict.fromkeys(response.sources))

    # 1. Check for PII / Internal Data Leakage or System Prompt Leakage
    if check_pii_leakage(response.text) or check_system_prompt_leakage(response.text):
        return AgentResponse(
            text="I cannot disclose confidential customer details, account holder names, recipient names, billing/shipping addresses, payment methods, security assessment data, internal support notes, or internal order flags. I can only provide customer-safe order status information. I recommend contacting support if you need further verification.",
            sources=[],
            status=ResponseStatus.REFUSED,
            handoff_reason=HandoffReason.PRIVACY_REFUSAL
        )

    # 2. Validate Citations
    if response.sources:
        valid_sources, all_ok = validate_citations(response, retrieved_results)
        response.sources = list(dict.fromkeys(valid_sources))

    return response
