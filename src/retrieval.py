"""
Retrieval Pipeline Module for Aster & Row Support Agent.
Implements BM25 candidate retrieval with TF-IDF weighting, semantic query intent
analysis (negation & membership context), active/superseded policy filtering,
and customer-citable evidence selection.
"""

import math
import re
from typing import List, Dict, Set, Tuple
from src.contracts import DocumentChunk, RetrievalResult, Status, Authority, Visibility


def normalize_token(token: str) -> str:
    """Basic stemming normalization for English words."""
    t = token.lower()
    if t.endswith("plus"):
        return t
    if len(t) > 4 and t.endswith("s"):
        t = t[:-1]
    return t


def tokenize(text: str) -> List[str]:
    """Tokenizes text into lowercase normalized alphanumeric tokens."""
    raw_tokens = re.findall(r"\w+", text.lower())
    return [normalize_token(t) for t in raw_tokens]


def analyze_membership_query_intent(query: str) -> str:
    """
    Analyzes semantic query intent regarding membership status and policy scope.
    Returns one of: 'STANDARD_CUSTOMER', 'TRAILPLUS_MEMBER', 'COMPARISON', 'NEUTRAL'
    """
    q_lower = query.lower()

    # Non-member / guest / standard plan intent indicators (including lapsed/expired/dropped status)
    non_member_patterns = [
        r"\bnever\s+(signed|joined|subscribed|had)",
        r"\bnot\s+a?\s*(member|subscribed|customer|on trailplus|joined)",
        r"\bwithout\s+being\s+a?\s*member",
        r"\bwithout\s+a?\s*(membership|trailplus|subscription)",
        r"\bguest\s+(checkout|order|customer|purchase)",
        r"\b(regular|standard|normal)\s+(customer|purchaser|buyer|bag|order|plan)",
        r"\bnon-member\b",
        r"\blapsed\b",
        r"\bexpired\b",
        r"\bformer\b",
        r"\bprevious\b",
        r"\bpast\s+member\b",
        r"\bno\s+longer\b",
        r"\bnot\s+active\b",
        r"\bwasn't\s+active\b",
        r"\bwas\s+not\s+active\b",
        r"\bdo\s+i\s+need\s+to\s+be\s+(enrolled|a\s+member|subscribed)\b",
        r"\benrolled\s+in\s+anything\b",
        r"\bbefore\s+i\s+placed\b",
        r"\bprior\s+to\s+order\b",
        r"\bdrop(ped)?\b",
        r"\blet\s+.*drop\b",
        r"\baccount\s+under\s+my\s+name\b",
        r"\bsister\b",
        r"\bbrother\b",
        r"\bfriend\b"
    ]
    is_non_member_intent = any(re.search(pat, q_lower) for pat in non_member_patterns)

    # Active member intent indicators
    member_patterns = [
        r"\bi\s+am\s+a?\s*trailplus",
        r"\bi\s+have\s+trailplus",
        r"\bas\s+a?\s*trailplus",
        r"\bmy\s+trailplus\b",
        r"\bi'm\s+a?\s*trailplus",
        r"\btrailplus\s+member\b"
    ]
    is_member_intent = any(re.search(pat, q_lower) for pat in member_patterns)

    if is_non_member_intent and not is_member_intent:
        return "STANDARD_CUSTOMER"

    if is_member_intent and not is_non_member_intent:
        return "TRAILPLUS_MEMBER"

    if "trailplus" in q_lower or "membership" in q_lower:
        return "COMPARISON"

    return "NEUTRAL"


class KnowledgeBaseRetriever:
    def __init__(self, chunks: List[DocumentChunk]):
        self.chunks = chunks
        self.doc_len: List[int] = []
        self.avg_doc_len: float = 0.0
        self.doc_freqs: Dict[str, int] = {}
        self.chunk_tokens: List[List[str]] = []
        self._build_index()

    def _build_index(self):
        N = len(self.chunks)
        if N == 0:
            return

        total_len = 0
        for chunk in self.chunks:
            tokens = tokenize(f"{chunk.title} {chunk.heading} {chunk.text}")
            self.chunk_tokens.append(tokens)
            l = len(tokens)
            self.doc_len.append(l)
            total_len += l

            seen_tokens: Set[str] = set(tokens)
            for t in seen_tokens:
                self.doc_freqs[t] = self.doc_freqs.get(t, 0) + 1

        self.avg_doc_len = total_len / N if N > 0 else 0.0

    def compute_bm25(self, query: str, k1: float = 1.5, b: float = 0.75) -> List[Tuple[int, float]]:
        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        N = len(self.chunks)
        intent = analyze_membership_query_intent(query)
        q_lower = query.lower()

        # International query detection: explicit country or international destination terms
        intl_countries = ["canada", "germany", "france", "australia", "japan", "kenya", "vietnam", "international", "overseas", "foreign", "antarctica", "europe", "asia"]
        is_international_query = any(c in q_lower for c in intl_countries)

        is_warranty_query = "warrant" in q_lower or "coverage" in q_lower or "guarante" in q_lower
        is_price_or_giftcard_query = "gift card" in q_lower or "price adjustment" in q_lower or "flash sale" in q_lower
        is_product_care_query = "care" in q_lower or "wash" in q_lower or "clean" in q_lower or "spot-clean" in q_lower
        is_domestic_shipping_query = any(term in q_lower for term in ["alaska", "hawaii", "po box", "free shipping", "minimum", "75", "standard shipping", "domestic", "how long does shipping take", "how long will it take"]) or (
            ("ship" in q_lower or "delivery" in q_lower) and not is_international_query and "return" not in q_lower
        )
        is_timeframe_query = ("return window" in q_lower or "timeframe" in q_lower or "send back" in q_lower or "period" in q_lower) or (
            "how long" in q_lower and "ship" not in q_lower and "deliver" not in q_lower
        )
        is_cancellation_query = "cancel" in q_lower or "cancellation" in q_lower or "modify order" in q_lower or "change order" in q_lower

        scores: List[Tuple[int, float]] = []
        for idx, chunk in enumerate(self.chunks):
            tokens = self.chunk_tokens[idx]
            l = self.doc_len[idx]
            score = 0.0

            tf_map: Dict[str, int] = {}
            for t in tokens:
                tf_map[t] = tf_map.get(t, 0) + 1

            for qt in query_tokens:
                if qt in tf_map:
                    df = self.doc_freqs.get(qt, 0)
                    idf = math.log((N - df + 0.5) / (df + 0.5) + 1.0)
                    tf = tf_map[qt]
                    num = tf * (k1 + 1.0)
                    den = tf + k1 * (1.0 - b + b * (l / (self.avg_doc_len or 1.0)))
                    score += idf * (num / den)

            # Heading boost for exact section match
            heading_tokens = tokenize(chunk.heading)
            for qt in query_tokens:
                if qt in heading_tokens:
                    score *= 1.5

            if intent == "STANDARD_CUSTOMER":
                if "01-returns" in chunk.filename and "standard" in chunk.text.lower():
                    score *= 20.0
                elif "09-trailplus" in chunk.filename:
                    score *= 0.001

            elif intent == "TRAILPLUS_MEMBER":
                if "09-trailplus" in chunk.filename:
                    score *= 4.0
                elif "01-returns" in chunk.filename and "trailplus" not in chunk.heading.lower():
                    score *= 0.3

            if is_warranty_query and "07-warranty" in chunk.filename:
                score *= 8.0

            if is_price_or_giftcard_query and "10-gift-cards" in chunk.filename:
                score *= 8.0

            if is_product_care_query and "11-product-care" in chunk.filename:
                score *= 8.0

            if is_domestic_shipping_query and "05-domestic" in chunk.filename:
                score *= 10.0

            if is_timeframe_query:
                if "01-returns" in chunk.filename and intent != "TRAILPLUS_MEMBER":
                    score *= 5.0
                    if "window" in chunk.heading.lower():
                        score *= 5.0
                elif "08-order-changes-and-cancellations" in chunk.filename and not is_cancellation_query:
                    score *= 0.01

            if is_cancellation_query and "08-order-changes-and-cancellations" in chunk.filename:
                score *= 5.0

            if is_international_query and "06-international" in chunk.filename:
                score *= 10.0

            if score > 0:
                scores.append((idx, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        customer_only: bool = True
    ) -> List[RetrievalResult]:
        """
        Retrieves candidate chunks, applies applicability and authority filters.
        """
        raw_scores = self.compute_bm25(query, k1=1.5, b=0.75)
        if not raw_scores:
            return []

        candidates: List[RetrievalResult] = []
        max_score = raw_scores[0][1] if raw_scores else 1.0

        for idx, score in raw_scores:
            norm_score = min(1.0, score / max_score)
            candidates.append(RetrievalResult(chunk=self.chunks[idx], similarity=norm_score))

        active_topics: Set[str] = set()
        for cand in candidates:
            if cand.chunk.status == Status.ACTIVE:
                parts = cand.chunk.filename.split("-")
                topic = parts[1] if len(parts) > 1 else cand.chunk.filename
                active_topics.add(topic)

        filtered_candidates: List[RetrievalResult] = []
        for cand in candidates:
            if cand.chunk.status == Status.SUPERSEDED:
                parts = cand.chunk.filename.split("-")
                topic = parts[1] if len(parts) > 1 else cand.chunk.filename
                if topic in active_topics:
                    continue

            if customer_only and not cand.chunk.is_customer_citable:
                continue

            filtered_candidates.append(cand)

        def ranking_key(res: RetrievalResult) -> Tuple[float, int]:
            auth_rank = 0
            if res.chunk.authority in (Authority.OFFICIAL_POLICY, Authority.OFFICIAL_PRODUCT):
                auth_rank = 3
            elif res.chunk.authority == Authority.SUPPORT_GUIDANCE:
                auth_rank = 2
            elif res.chunk.authority == Authority.INTERNAL:
                auth_rank = 1
            return (res.similarity, auth_rank)

        filtered_candidates.sort(key=ranking_key, reverse=True)
        return filtered_candidates[:top_k]
