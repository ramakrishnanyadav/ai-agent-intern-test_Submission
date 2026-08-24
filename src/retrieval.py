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
        r"\bfree\s+tier\b",
        r"\b(sister|friend|brother|partner|relative|mother|father|family)\s+has\b",
        r"\bunder\s+my\s+name\b"
    ]
    is_non_member = any(re.search(pat, q_lower) for pat in non_member_patterns)

    # General negation combined with membership terms
    has_negation = any(neg in q_lower for neg in ["never", "not", "without", "don't", "no ", "lapsed", "expired", "former", "previous", "drop", "dropped", "free tier"])
    has_loyalty_term = any(term in q_lower for term in ["membership", "loyalty", "trailplus", "subscription", "member", "enrolled"])

    if has_negation and has_loyalty_term and not re.search(r"\bis\s+active\b", q_lower):
        is_non_member = True

    # Comparative query indicators
    is_comparison = any(phrase in q_lower for phrase in [
        "same return", "same window", "difference between", "compared to", "vs", "versus"
    ]) and has_loyalty_term

    if is_comparison:
        return "COMPARISON"
    elif is_non_member:
        return "STANDARD_CUSTOMER"
    elif "trailplus" in q_lower or "membership" in q_lower:
        return "TRAILPLUS_MEMBER"
    
    return "NEUTRAL"


class KnowledgeBaseRetriever:
    def __init__(self, chunks: List[DocumentChunk]):
        self.chunks = chunks
        self.doc_token_counts: List[Dict[str, int]] = []
        self.doc_lengths: List[int] = []
        self.df: Dict[str, int] = {}
        self.N = len(chunks)
        self._build_index()

    def _build_index(self):
        for chunk in self.chunks:
            tokens = tokenize(f"{chunk.title} {chunk.heading} {chunk.text}")
            token_counts: Dict[str, int] = {}
            for t in tokens:
                token_counts[t] = token_counts.get(t, 0) + 1
            self.doc_token_counts.append(token_counts)
            self.doc_lengths.append(len(tokens))

            # Document frequency
            unique_tokens = set(tokens)
            for ut in unique_tokens:
                self.df[ut] = self.df.get(ut, 0) + 1

    def compute_bm25(self, query: str, k1: float = 1.5, b: float = 0.75) -> List[Tuple[int, float]]:
        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        avg_dl = sum(self.doc_lengths) / max(1, self.N)
        scores: List[Tuple[int, float]] = []

        q_lower = query.lower()
        intent = analyze_membership_query_intent(query)

        is_warranty_query = any(phrase in q_lower for phrase in ["warranty", "guarantee", "lifetime"])
        is_price_or_giftcard_query = any(phrase in q_lower for phrase in ["gift card", "gift cards", "price adjustment", "price drop", "price went down", "difference", "cheaper now", "flash sale", "expire"])
        is_product_care_query = any(phrase in q_lower for phrase in ["wash", "washing", "spot-clean", "spot clean", "dry", "tumble dry", "cleaning", "care"])
        
        intl_terms = [
            "canada", "germany", "france", "australia", "japan", "uk", "england",
            "britain", "spain", "italy", "mexico", "brazil", "kenya", "vietnam", "europe", "asia",
            "antarctica", "international", "overseas", "foreign", "abroad", "outside us", "outside the us"
        ]
        has_intl_country = any(term in q_lower for term in intl_terms)
        # Stemmed verb matching for ship/send/deliver in any tense (shipped, shipping, sends, delivered, etc.)
        has_send_to = bool(re.search(r"\b(ship|send|deliver)\w*\b.*\bto\b", q_lower))
        is_international_query = has_intl_country or (has_send_to and not re.search(r"\b(us|usa|united states|hawaii|alaska|po box|p\.o\. box)\b", q_lower))

        is_shipping_timeline_query = any(phrase in q_lower for phrase in [
            "shipping take", "delivery take", "arrive in", "ship to hawaii", "ship to alaska",
            "po box", "shipping timeline", "shipping charges", "free shipping", "minimum spend"
        ]) and not is_international_query

        is_timeframe_query = any(phrase in q_lower for phrase in [
            "how long", "how many days", "return window", "timeframe", "deadline",
            "send it back", "send back", "sending something back", "sending back", "return an item",
            "time to send", "how much time", "get 30 days", "return my order", "return my"
        ]) and not is_warranty_query and not is_shipping_timeline_query and not is_product_care_query and not is_international_query

        is_cancellation_query = any(phrase in q_lower for phrase in ["cancel", "cancellation", "cancel my order"])

        for idx, chunk in enumerate(self.chunks):
            doc_len = self.doc_lengths[idx]
            doc_counts = self.doc_token_counts[idx]
            score = 0.0

            title_tokens = set(tokenize(f"{chunk.title} {chunk.heading}"))

            for qt in query_tokens:
                if qt in doc_counts:
                    freq = doc_counts[qt]
                    doc_freq = self.df.get(qt, 0)
                    idf = math.log((self.N - doc_freq + 0.5) / (doc_freq + 0.5) + 1.0)
                    tf_norm = (freq * (k1 + 1)) / (freq + k1 * (1 - b + b * (doc_len / avg_dl)))
                    
                    term_score = idf * tf_norm
                    if qt in title_tokens:
                        term_score *= 2.0
                    score += term_score

            # Apply intent-guided domain authority weighting
            if intent == "STANDARD_CUSTOMER":
                if "01-returns" in chunk.filename:
                    score *= 4.0
                    if "window" in chunk.heading.lower():
                        score *= 5.0
                elif "09-trailplus" in chunk.filename:
                    score *= 0.05

            elif intent == "TRAILPLUS_MEMBER":
                if "09-trailplus" in chunk.filename:
                    score *= 5.0

            elif intent == "COMPARISON":
                if "01-returns" in chunk.filename or "09-trailplus" in chunk.filename:
                    score *= 3.0

            if is_warranty_query and "07-warranty" in chunk.filename:
                score *= 8.0

            if is_price_or_giftcard_query and "10-gift-cards" in chunk.filename:
                score *= 8.0

            if is_product_care_query and "11-product-care" in chunk.filename:
                score *= 8.0

            if is_shipping_timeline_query and "05-domestic" in chunk.filename:
                score *= 8.0

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
