"""
Scoped Conflict Detector Module for Aster & Row Support Agent.
Normalizes structured facts from active retrieved chunks and detects genuine conflicts.
"""

import re
from typing import List, Optional, Tuple, Any
from src.contracts import RetrievalResult, PolicyFact, Status, Authority


def normalize_supported_policy_facts(results: List[RetrievalResult], user_message: str = "") -> List[PolicyFact]:
    """
    Extracts structured policy facts from retrieved chunks for known comparison domains.
    Checks user_message intent so that false conflicts are not generated on unrelated questions.
    """
    facts: List[PolicyFact] = []
    msg_lower = user_message.lower()

    # 1. Breeze Tumbler dishwasher safety domain
    is_dishwasher_query = not user_message or any(w in msg_lower for w in ["dishwasher", "dish-washer", "wash", "clean", "care", "tumbler"])
    is_warranty_query = "warranty" in msg_lower or "guarantee" in msg_lower

    if is_dishwasher_query and not is_warranty_query:
        for res in results:
            chunk = res.chunk
            text_lower = chunk.text.lower()

            if "tumbler" in text_lower or "breeze" in text_lower:
                if "hand-wash" in text_lower or "hand-washed" in text_lower or "hand wash" in text_lower:
                    if "body" in text_lower:
                        facts.append(
                            PolicyFact(
                                subject="dishwasher",
                                product="Breeze Tumbler",
                                component="body",
                                condition="dishwasher_safe",
                                value=False,
                                scope="hand_wash_body",
                                source_filename=chunk.filename,
                                source_heading=f"{chunk.filename}"
                            )
                        )
                if "all components are dishwasher safe" in text_lower or "all components" in text_lower:
                    facts.append(
                        PolicyFact(
                            subject="dishwasher",
                            product="Breeze Tumbler",
                            component="all",
                            condition="dishwasher_safe",
                            value=True,
                            scope="all_dishwasher_safe",
                            source_filename=chunk.filename,
                            source_heading=f"{chunk.filename}"
                        )
                    )

    # 2. Return window days domain
    if not user_message or ("return" in msg_lower and ("day" in msg_lower or "days" in msg_lower or "window" in msg_lower)):
        for res in results:
            chunk = res.chunk
            text_lower = chunk.text.lower()
            if "30 calendar days" in text_lower or "30 days" in text_lower:
                facts.append(
                    PolicyFact(
                        subject="returns",
                        product="standard_merchandise",
                        component=None,
                        condition="return_window_days",
                        value=30,
                        scope="standard_customer",
                        source_filename=chunk.filename,
                        source_heading=f"{chunk.filename}"
                    )
                )
            if "45 calendar days" in text_lower or "45 days" in text_lower:
                scope = "trailplus_member" if "trailplus" in text_lower or "membership" in text_lower else "legacy_policy"
                facts.append(
                    PolicyFact(
                        subject="returns",
                        product="standard_merchandise",
                        component=None,
                        condition="return_window_days",
                        value=45,
                        scope=scope,
                        source_filename=chunk.filename,
                        source_heading=f"{chunk.filename}"
                    )
                )

    return facts


def compare_facts(facts: List[PolicyFact]) -> Optional[Tuple[PolicyFact, PolicyFact]]:
    """
    Compares normalized facts across active official sources.
    Returns (fact_a, fact_b) if a genuine conflict exists; otherwise None.
    """
    grouped: dict = {}
    for fact in facts:
        key = (fact.subject, fact.product)
        grouped.setdefault(key, []).append(fact)

    for (subject, product), fact_list in grouped.items():
        if len(fact_list) < 2:
            continue

        if subject == "dishwasher" and product == "Breeze Tumbler":
            has_body_false = any(f.component == "body" and f.value is False for f in fact_list)
            has_all_true = any(f.component == "all" and f.value is True for f in fact_list)
            if has_body_false and has_all_true:
                fact_a = next(f for f in fact_list if f.component == "body")
                fact_b = next(f for f in fact_list if f.component == "all")
                return (fact_a, fact_b)

        if subject == "returns":
            std_facts = [f for f in fact_list if f.scope == "standard_customer"]
            values = set(f.value for f in std_facts)
            if len(values) > 1:
                return (std_facts[0], std_facts[1])

    return None
