"""
Regression test suite catching bugs documented in the Bug Diary.
"""

import unittest
from pathlib import Path
from src.ingestion import chunk_markdown_document
from src.retrieval import KnowledgeBaseRetriever, normalize_token
from src.tools import OrderLookupTool
from src.agent import AsterRowSupportAgent


class TestBugDiaryRegressions(unittest.TestCase):

    def test_regression_bug1_token_stemming(self):
        """
        Regression Test for Bug 1: Token stemming / normalization.
        'returns' and 'return' should normalize to the same root 'return'.
        """
        self.assertEqual(normalize_token("returns"), "return")
        self.assertEqual(normalize_token("backpacks"), "backpack")

    def test_regression_bug2_preamble_heading_chunking(self):
        """
        Regression Test for Bug 2: Preamble heading chunking.
        Markdown documents with `# Title` followed by `## Section` should not create
        an empty standalone preamble chunk.
        """
        sample_doc = """---
document_id: TEST-REG
title: Test Title
status: active
audience: customer
policy_authority: official
---

# Test Title

## Section One

Content one.
"""
        chunks = chunk_markdown_document("test.md", "test.md", sample_doc)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].heading, "Section One")

    def test_regression_bug3_cancelled_order_stale_eta(self):
        """
        Regression Test for Bug 3: Cancelled order stale delivery estimate leak.
        ORD-1004 has status 'cancelled' but contains estimated_delivery '2026-08-16'.
        The tool MUST override delivery_estimate to None.
        """
        tool = OrderLookupTool("data/orders.json")
        result = tool.lookup("ORD-1004")
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "cancelled")
        self.assertIsNone(result.delivery_estimate, "Stale ETA on cancelled order was not overridden to None!")

    def test_regression_bug4_cancellation_filename_reference(self):
        """
        Regression Test for Bug 4: Cancellation policy filename reference bug.
        Ensures cancellation queries boost '08-order-changes-and-cancellations.md'.
        """
        agent = AsterRowSupportAgent()
        res = agent.retriever.retrieve("cancel my order", top_k=2)
        self.assertTrue(any("08-order-changes-and-cancellations" in r.chunk.filename for r in res))

    def test_regression_bug5_unlisted_country_shipping(self):
        """
        Regression Test for Bug 5: Unlisted country shipping generalization (France, Vietnam, Kenya).
        Queries about shipping to unlisted countries MUST retrieve 06-international-shipping.md
        and yield ANSWERED status, rather than improper final-sale or insufficient-evidence fallback.
        """
        agent = AsterRowSupportAgent()
        for country_query in [
            "Can you send an Atlas Weekender to France?",
            "Can I get this shipped to Vietnam?",
            "Do you deliver to Kenya?"
        ]:
            res = agent.process_message(country_query)
            self.assertEqual(res.status.value, "ANSWERED")
            self.assertIn("06-international-shipping.md", res.sources)
            self.assertNotIn("03-final-sale-and-promotions.md", res.sources)
            self.assertNotIn("10-gift-cards-and-price-adjustments.md", res.sources)

    def test_regression_bug6_citation_source_mismatch(self):
        """
        Regression Test for Bug 6: Citation source mismatch prevention.
        Sources returned in AgentResponse MUST be strictly referenced/cited in the response text.
        """
        agent = AsterRowSupportAgent()
        res = agent.process_message("I let my TrailPlus membership drop, what return window applies?")
        self.assertEqual(res.sources, ["01-returns-policy-current.md"])
        self.assertNotIn("08-order-changes-and-cancellations.md", res.sources)


if __name__ == "__main__":
    unittest.main()
