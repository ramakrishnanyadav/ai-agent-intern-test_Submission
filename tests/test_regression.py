"""
Regression test suite catching bugs documented in the Bug Diary.
"""

import unittest
from pathlib import Path
from src.ingestion import chunk_markdown_document
from src.retrieval import KnowledgeBaseRetriever, normalize_token
from src.tools import OrderLookupTool


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


if __name__ == "__main__":
    unittest.main()
