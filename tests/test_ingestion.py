

"""
Unit tests for knowledge base ingestion and chunking.
"""

import os
import unittest
from pathlib import Path
from src.ingestion import parse_frontmatter, map_metadata_to_enums, chunk_markdown_document, load_knowledge_base
from src.contracts import Status, Authority, Visibility


class TestIngestion(unittest.TestCase):

    def setUp(self):
        self.kb_dir = Path("knowledge-base")

    def test_parse_frontmatter(self):
        sample_doc = """---
document_id: TEST-01
title: Test Document
status: active
audience: customer
policy_authority: official
---

# Test Title

## Standard Section

This is test text.
"""
        metadata, body = parse_frontmatter(sample_doc)
        self.assertEqual(metadata.get("document_id"), "TEST-01")
        self.assertEqual(metadata.get("status"), "active")
        self.assertIn("# Test Title", body)

    def test_map_metadata_enums(self):
        # Current Active Document
        meta_active = {"status": "active", "audience": "customer", "policy_authority": "official"}
        status, authority, visibility = map_metadata_to_enums(meta_active, "01-returns-policy-current.md")
        self.assertEqual(status, Status.ACTIVE)
        self.assertEqual(authority, Authority.OFFICIAL_POLICY)
        self.assertEqual(visibility, Visibility.CUSTOMER)

        # Legacy Document
        meta_legacy = {"status": "superseded", "audience": "customer", "policy_authority": "official"}
        status, authority, visibility = map_metadata_to_enums(meta_legacy, "02-returns-policy-legacy.md")
        self.assertEqual(status, Status.SUPERSEDED)

        # Internal Migration Note
        meta_internal = {"status": "draft", "audience": "internal", "policy_authority": "none", "customer_answering": False}
        status, authority, visibility = map_metadata_to_enums(meta_internal, "14-internal-content-migration-notes.md")
        self.assertEqual(status, Status.DRAFT)
        self.assertEqual(authority, Authority.INTERNAL)
        self.assertEqual(visibility, Visibility.INTERNAL)

    def test_chunk_markdown_document(self):
        sample = """---
document_id: RET-2026-01
title: Returns Policy
status: active
audience: customer
policy_authority: official
---

# Returns Policy

## Standard return window

Customers may request a return within 30 calendar days of delivery.

## Exclusions and exceptions

Final-sale items and gift cards are not returnable for a change of mind.
"""
        chunks = chunk_markdown_document("fake/path.md", "01-returns.md", sample)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].heading, "Standard return window")
        self.assertEqual(chunks[1].heading, "Exclusions and exceptions")
        self.assertTrue(chunks[0].is_customer_citable)
        self.assertIn("30 calendar days", chunks[0].text)
        # Verify title context is included
        self.assertIn("# Returns Policy", chunks[0].text)

    def test_load_entire_knowledge_base(self):
        if not self.kb_dir.exists():
            self.skipTest("knowledge-base directory not found")
        chunks = load_knowledge_base(str(self.kb_dir))
        self.assertGreater(len(chunks), 15)
        
        # Verify 01-returns-policy-current is loaded with active status
        current_chunks = [c for c in chunks if c.filename == "01-returns-policy-current.md"]
        self.assertTrue(all(c.status == Status.ACTIVE for c in current_chunks))
        self.assertTrue(all(c.is_customer_citable for c in current_chunks))

        # Verify 14-internal is loaded as INTERNAL visibility
        internal_chunks = [c for c in chunks if c.filename == "14-internal-content-migration-notes.md"]
        self.assertTrue(all(c.visibility == Visibility.INTERNAL for c in internal_chunks))
        self.assertFalse(any(c.is_customer_citable for c in internal_chunks))


if __name__ == "__main__":
    unittest.main()
