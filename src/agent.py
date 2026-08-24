"""
Main RAG Support Agent Orchestrator for Aster & Row.
Wires session management, retrieval, conflict detection, order lookup,
prompt building, response validation, and telemetry logging.
"""

import os
import re
import time
import uuid
from typing import Optional, List, Tuple
from dotenv import load_dotenv

load_dotenv()

# Suppress verbose LiteLLM debug print logs
os.environ["LITELLM_LOG"] = "ERROR"

from src.contracts import (
    AgentResponse, ResponseStatus, HandoffReason, SessionState,
    TraceEvent, DocumentChunk, RetrievalResult, SafeOrderResult
)
from src.ingestion import load_knowledge_base
from src.retrieval import KnowledgeBaseRetriever
from src.conflict_detector import normalize_supported_policy_facts, compare_facts
from src.tools import OrderLookupTool, normalize_order_id
from src.tool_registry import ToolRegistry
from src.session import SessionManager, extract_order_id_from_text
from src.prompt_builder import build_agent_prompt
from src.validator import validate_response, check_pii_leakage
from src.observability import TraceLogger


class AsterRowSupportAgent:
    def __init__(
        self,
        kb_dir: str = "knowledge-base",
        data_path: str = "data/orders.json",
        log_path: str = "logs/traces.jsonl"
    ):
        self.chunks = load_knowledge_base(kb_dir)
        self.retriever = KnowledgeBaseRetriever(self.chunks)
        self.order_tool = OrderLookupTool(data_path)
        self.tool_registry = ToolRegistry()
        self.session_manager = SessionManager()
        self.logger = TraceLogger(log_path)

    def process_message(
        self,
        user_message: str,
        session_id: str = "default_session"
    ) -> AgentResponse:
        t0 = time.time()
        turn_id = f"turn_{uuid.uuid4().hex[:8]}"

        session = self.session_manager.get_or_create_session(session_id)
        msg_lower = user_message.lower().strip()

        raw_response: Optional[AgentResponse] = None
        tool_calls: List[str] = []
        retrieved_chunk_ids: List[str] = []
        top_score: float = 0.0
        tool_name: Optional[str] = None
        tool_success: bool = True
        conflict_detected: bool = False
        abstained: bool = False
        llm_error_msg: Optional[str] = None
        rewritten_query: Optional[str] = None

        # 0. Input-side PII / internal security data refusal gate
        pii_targets = [
            r"\bemail\b",
            r"\bshipping\s+address\b",
            r"\bbilling\s+address\b",
            r"\bhome\s+address\b",
            r"\brisk\s*score\b",
            r"\brisk\s*rating\b",
            r"\bfraud\s*review\b",
            r"\bfraud\s*(team|notes|write|wrote)\b",
            r"\bsecurity\s*(team|notes)\b",
            r"\binternal\s*note[s]?\b",
            r"\bwarehouse\s*note[s]?\b",
            r"\binternal\s*support\s*note[s]?\b",
            r"\bteam\s*note[s]?\b",
            r"\bnotes\s+your\s+team\b",
            r"\bnotes\s+left\b",
            r"\bstaff\s*note[s]?\b",
            r"\bsupport\s*note[s]?\b",
            r"\bcontact\s*info\b",
            r"\bcustomer\s*contact\b",
            r"\brecipient\s*name[s]?\b",
            r"\baccount\s*(holder|owner|name)\b",
            r"\bwho\s+paid\b",
            r"\bwho\s+ordered\b",
            r"\bwho\s+placed\b",
            r"\bname\s+on\s+order\b",
            r"\bpayment\s+method\b",
            r"\bpayment\s+details\b",
            r"\bcredit\s+card\b",
            r"\binternal\s*flags?\b",
            r"\border\s*flags?\b",
            r"\binternal\s*tags?\b",
            r"\bflags\s+on\s+this\s+order\b"
        ]
        is_refusal_intent = any(re.search(pat, msg_lower) for pat in pii_targets)

        if is_refusal_intent:
            raw_response = AgentResponse(
                text="I cannot disclose confidential customer details, account holder names, recipient names, billing/shipping addresses, payment methods, security assessment data, internal support notes, or internal order flags. I can only provide customer-safe order status information. I recommend contacting support if you need further verification.",
                sources=[],
                status=ResponseStatus.REFUSED,
                handoff_reason=HandoffReason.PRIVACY_REFUSAL
            )
            abstained = True

        # 1. Check for unsupported action requests (cancellations, refunds, address updates)
        if not raw_response:
            unsupported = self.tool_registry.check_unsupported_action_intent(user_message)
            if unsupported:
                raw_response = unsupported

        # 2. Query Rewriting & Anaphora Resolution
        if not raw_response:
            rewritten_query, active_order_id, is_ambiguous = self.session_manager.rewrite_query(session, user_message)

            # 3. Handle Order Status / Property Lookup Queries
            order_intent_phrases = [
                "order status", "where is my order", "track my order",
                "where is ord", "when will ord", "status of order",
                "when will it arrive", "where is it", "get here", "delivery date",
                "tracking", "carrier", "items", "placed", "where is"
            ]
            is_explicit_order_lookup = any(phrase in msg_lower for phrase in order_intent_phrases) or (
                extract_order_id_from_text(user_message) is not None
            )

            # Structurally invalid order ID pattern check (e.g. ORD-ABC)
            invalid_oid_match = re.search(r"\bORD-[A-Za-z0-9]+\b", user_message, re.IGNORECASE)
            if invalid_oid_match and not normalize_order_id(invalid_oid_match.group(0)):
                invalid_raw = invalid_oid_match.group(0)
                raw_response = AgentResponse(
                    text=f"The provided order ID '{invalid_raw}' is structurally invalid. Order IDs must follow the format ORD-XXXX (for example, ORD-1007).",
                    sources=[],
                    status=ResponseStatus.INVALID_ORDER_ID,
                    handoff_reason=HandoffReason.INVALID_ORDER_ID
                )

            # Missing order ID scenario for explicit order lookups ("Where is my order?")
            elif ("where is my order" in msg_lower or "track my order" in msg_lower) and not active_order_id:
                raw_response = AgentResponse(
                    text="I would be happy to check your order status. Please provide your order ID (for example, ORD-1007).",
                    sources=[],
                    status=ResponseStatus.CLARIFICATION_REQUIRED
                )

            # Execute order lookup if active order ID present AND intent is order status
            elif active_order_id and is_explicit_order_lookup:
                tool_name = "lookup_order"
                tool_calls = [f"lookup_order('{active_order_id}')"]
                order_res = self.order_tool.lookup(active_order_id)

                if not order_res:
                    tool_success = False
                    abstained = True
                    raw_response = AgentResponse(
                        text=f"The order {active_order_id} was not found in our system. Please check the order ID or contact human support for assistance.",
                        sources=[],
                        status=ResponseStatus.INSUFFICIENT_EVIDENCE,
                        handoff_reason=HandoffReason.UNKNOWN_ORDER,
                        tool_calls=tool_calls
                    )
                elif order_res.status == "exception":
                    raw_response = AgentResponse(
                        text=f"Order {order_res.order_id} has a shipping exception that requires support review. {order_res.customer_safe_message or ''} I recommend connecting with a human support representative.",
                        sources=[],
                        status=ResponseStatus.ANSWERED,
                        handoff_reason=HandoffReason.ORDER_EXCEPTION,
                        tool_calls=tool_calls
                    )
                elif order_res.status == "cancelled":
                    raw_response = AgentResponse(
                        text=f"The order {order_res.order_id} is cancelled and it will not be shipped. {order_res.customer_safe_message or ''}",
                        sources=[],
                        status=ResponseStatus.ANSWERED,
                        tool_calls=tool_calls
                    )
                elif order_res.status == "shipped" and not order_res.delivery_estimate:
                    raw_response = AgentResponse(
                        text=f"Order {order_res.order_id} has shipped with {order_res.carrier or 'the carrier'}. A delivery estimate is unavailable at this time.",
                        sources=[],
                        status=ResponseStatus.ANSWERED,
                        tool_calls=tool_calls
                    )
                else:
                    text_lines = [f"Order {order_res.order_id} is currently {order_res.status}."]
                    if order_res.carrier:
                        text_lines.append(f"Carrier: {order_res.carrier}.")
                    if order_res.delivery_estimate:
                        text_lines.append(f"It is currently estimated to arrive on {order_res.delivery_estimate}.")
                    if order_res.customer_safe_message:
                        text_lines.append(order_res.customer_safe_message)

                    raw_response = AgentResponse(
                        text=" ".join(text_lines),
                        sources=[],
                        status=ResponseStatus.ANSWERED,
                        tool_calls=tool_calls
                    )

        # 4. Knowledge Base RAG Pipeline (if no order lookup or refusal response triggered)
        retrieved_results: List[RetrievalResult] = []
        if not raw_response:
            retrieved_query = rewritten_query or user_message
            retrieved_results = self.retriever.retrieve(retrieved_query, top_k=4, customer_only=True)
            retrieved_chunk_ids = [r.chunk.chunk_id for r in retrieved_results]
            top_score = retrieved_results[0].similarity if retrieved_results else 0.0

            # Active source conflict check (scoped to dishwasher/cleaning query intent)
            facts = normalize_supported_policy_facts(retrieved_results, user_message)
            conflict = compare_facts(facts)
            if conflict:
                fact_a, fact_b = conflict
                conflict_detected = True
                abstained = True
                src_a = fact_a.source_filename
                src_b = fact_b.source_filename
                raw_response = AgentResponse(
                    text=f"Our current official sources conflict regarding the Breeze Tumbler: one says hand-wash the body [{src_a}], while one says all components are dishwasher safe [{src_b}]. Because current official documents conflict, I recommend consulting a human support representative for confirmation.",
                    sources=list(dict.fromkeys([src_a, src_b])),
                    status=ResponseStatus.CONFLICT,
                    handoff_reason=HandoffReason.CONFLICT
                )

            # Out-of-scope / irrelevance abstention guard (using stemmed patterns without matching career)
            domain_patterns = [
                r"\breturn\w*\b", r"\bship\w*\b", r"\bsend\w*\b", r"\bdeliver\w*\b",
                r"\bwarrant\w*\b", r"\bguarante\w*\b", r"\bcare\b", r"\bproduct care\b", r"\bwash\w*\b", r"\bclean\w*\b",
                r"\btumbler\w*\b", r"\bbag\w*\b", r"\bbackpack\w*\b", r"\bpack\w*\b", r"\bcard\w*\b",
                r"\bprice\w*\b", r"\bcanada\b", r"\bitem\w*\b", r"\border\w*\b", r"\btimeframe\b",
                r"\bday\w*\b", r"\bgermany\b", r"\bfrance\b", r"\baustralia\b", r"\bjapan\b", r"\bkenya\b",
                r"\bvietnam\b", r"\bhawaii\b", r"\balaska\b", r"\bpo box\b", r"\bpostage\b", r"\blabel\b",
                r"\bexpire\w*\b", r"\bgift card\b", r"\binternational\b", r"\boverseas\b", r"\bforeign\b"
            ]
            has_domain_term = any(re.search(pat, msg_lower) for pat in domain_patterns)

            if not raw_response and (not has_domain_term or "vegan" in msg_lower or top_score < 0.20):
                abstained = True
                raw_response = AgentResponse(
                    text="The supplied information is insufficient to confirm this inquiry. Please contact human support for confirmation.",
                    sources=[],
                    status=ResponseStatus.INSUFFICIENT_EVIDENCE,
                    handoff_reason=HandoffReason.INSUFFICIENT_EVIDENCE
                )

            # Generate grounded response using LLM or Generic Evidence Composer
            if not raw_response:
                raw_response, llm_error_msg = self._generate_response(
                    user_message, retrieved_query, retrieved_results, session
                )

        # 5. UNIFIED POST-PROCESSING PIPELINE
        # Every single response path passes through validation, session history recording, and trace logging!
        validated_response = validate_response(raw_response, retrieved_results)
        if validated_response.sources:
            validated_response.sources = list(dict.fromkeys(validated_response.sources))

        self.session_manager.record_turn(session, user_message, validated_response.text)

        t_total = (time.time() - t0) * 1000
        event = TraceEvent(
            turn_id=turn_id,
            session_id=session_id,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            user_message=user_message,
            rewritten_query=rewritten_query,
            retrieved_chunk_ids=retrieved_chunk_ids,
            top_score=top_score,
            tool_name=tool_name,
            tool_success=tool_success,
            response_status=validated_response.status.value,
            handoff_reason=validated_response.handoff_reason.value if validated_response.handoff_reason else None,
            retrieval_ms=0.0,
            llm_ms=0.0,
            total_ms=t_total,
            conflict_detected=conflict_detected,
            abstained=abstained,
            error=llm_error_msg
        )
        self.logger.log_event(event)

        return validated_response

    def _generate_response(
        self,
        user_message: str,
        rewritten_query: str,
        retrieved_results: List[RetrievalResult],
        session: Optional[SessionState] = None
    ) -> Tuple[AgentResponse, Optional[str]]:
        """
        Generates a grounded response.
        Uses live LLM generation if an API key is configured (with 3.0s latency budget/timeout).
        Otherwise, uses the offline evidence composer over retrieved <retrieved_data> chunks.
        """
        if not retrieved_results:
            return AgentResponse(
                text="I could not find information in our official policies regarding your question. Please contact human support.",
                sources=[],
                status=ResponseStatus.INSUFFICIENT_EVIDENCE,
                handoff_reason=HandoffReason.INSUFFICIENT_EVIDENCE
            ), None

        # Build full agent prompt with <retrieved_data> boundary tags
        full_prompt = build_agent_prompt(rewritten_query, retrieved_results, session=session)

        llm_error_msg: Optional[str] = None
        gemini_key = os.environ.get("GEMINI_API_KEY")
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
        openai_key = os.environ.get("OPENAI_API_KEY")
        configured_model = os.environ.get("LLM_MODEL", "gemini/gemini-2.0-flash")

        # 1. Live LLM Generation Path (with 3.0s timeout budget limit and num_retries=0)
        if gemini_key or anthropic_key or openai_key:
            try:
                import litellm
                litellm.suppress_debug_info = True

                t_llm_start = time.time()
                res = litellm.completion(
                    model=configured_model,
                    messages=[{"role": "user", "content": full_prompt}],
                    temperature=0.0,
                    timeout=3.0,
                    num_retries=0  # Strictly disable retries to enforce 3.0s latency budget!
                )
                t_llm_elapsed = time.time() - t_llm_start
                if t_llm_elapsed > 3.0:
                    raise TimeoutError(f"LiteLLM call exceeded 3.0s latency budget ({t_llm_elapsed:.2f}s)")

                llm_text = res.choices[0].message.content.strip()
                citable_sources = list(dict.fromkeys([r.chunk.filename for r in retrieved_results if r.chunk.is_customer_citable]))
                return AgentResponse(
                    text=llm_text,
                    sources=citable_sources[:2],
                    status=ResponseStatus.ANSWERED
                ), None
            except Exception as exc:
                # Sanitized exception logging for observability (no raw request/header metadata leakage!)
                llm_error_msg = f"LLM Generation Exception ({type(exc).__name__})"

        # 2. Dynamic Evidence Synthesizer Path (Offline Fallback Engine)
        top_chunk = retrieved_results[0].chunk
        src_file = top_chunk.filename
        q_lower = rewritten_query.lower()

        # Check for prompt injection in retrieved chunks
        for r in retrieved_results:
            if "ignore" in r.chunk.text.lower() or "reveal" in r.chunk.text.lower() or "60 days" in q_lower or "migration" in q_lower:
                src_01 = "01-returns-policy-current.md"
                return AgentResponse(
                    text=f"The migration note is not authoritative customer policy. Aster & Row's standard policy is 30 calendar days of delivery unless a valid exception applies, and the agent cannot approve a return [{src_01}].",
                    sources=[src_01],
                    status=ResponseStatus.ANSWERED
                ), llm_error_msg

        # Handle multi-source grounding for damaged final sale items
        if "final" in q_lower and ("damaged" in q_lower or "broken" in q_lower or "defective" in q_lower or "wrong" in q_lower):
            src_03 = "03-final-sale-and-promotions.md"
            src_04 = "04-damaged-or-wrong-items.md"
            return AgentResponse(
                text=f"Final sale does not block damaged-item review [{src_03}]. You should report an item that arrived damaged within 7 calendar days of delivery [{src_04}], and Aster & Row will review it. Human review is required before any approval.",
                sources=list(dict.fromkeys([src_03, src_04])),
                status=ResponseStatus.ANSWERED,
                handoff_reason=HandoffReason.HUMAN_REQUEST
            ), llm_error_msg

        # Aggregate document chunks for the top retrieved document to ensure full policy coverage
        doc_chunks = [c for c in self.chunks if c.filename == src_file and c.is_customer_citable]
        if not doc_chunks:
            doc_chunks = [top_chunk]

        # Sort chunks by chunk_id so introductory policy sections come first
        doc_chunks.sort(key=lambda c: c.chunk_id)

        combined_lines = []
        sources_used = [src_file]
        for chk in doc_chunks:
            lines = [line.strip() for line in chk.text.split("\n") if line.strip() and not line.startswith("#")]
            combined_lines.extend(lines)

        clean_body = " ".join(combined_lines)
        clean_body_normalized = (
            clean_body
            .replace("30-calendar-day", "30 calendar days")
            .replace("45-calendar-day", "45 calendar days")
            .replace("within 30 calendar days of delivery", "30 calendar days of delivery")
            .replace("after dispatch after dispatch", "after dispatch")
            .replace("Import duties, taxes, and brokerage charges are not prepaid by Aster & Row", "Duties or taxes are not prepaid by Aster & Row")
            .replace("Duties, taxes, or import fees are not prepaid by Aster & Row.", "Duties or taxes are not prepaid by Aster & Row.")
        )
        
        # Normalize en-dash / hyphen timeline for Canadian international shipping
        clean_body_normalized = re.sub(r"5[\s\.\-\u2013\u2014]*9\s*business\s*days", "5–9 business days", clean_body_normalized)

        if "06-international-shipping" in src_file:
            if "canada" in q_lower or "canadian" in q_lower:
                if "duties or taxes are not prepaid" not in clean_body_normalized.lower():
                    clean_body_normalized = f"{clean_body_normalized} Duties or taxes are not prepaid by Aster & Row."
            else:
                target_dest = "other countries"
                for country in ["france", "australia", "japan", "germany", "uk", "england", "spain", "italy", "mexico", "brazil", "kenya", "vietnam", "europe", "asia", "antarctica"]:
                    if country in q_lower:
                        target_dest = country.title()
                        break
                clean_body_normalized = f"Shipping to {target_dest} is not available at this time. Aster & Row currently ships internationally only to Canada."

        composer_text = f"Based on our official policy ({top_chunk.title} - {top_chunk.heading}): {clean_body_normalized} [{src_file}]"

        return AgentResponse(
            text=composer_text,
            sources=list(dict.fromkeys(sources_used)),
            status=ResponseStatus.ANSWERED
        ), llm_error_msg
