"""
Standalone unit tests for retrieval pipeline.
"""

import unittest
from pathlib import Path
from src.ingestion import load_knowledge_base
from src.retrieval import KnowledgeBaseRetriever
from src.contracts import Status, Authority, Visibility


class TestRetrieval(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        kb_path = Path("knowledge-base")
        if kb_path.exists():
            cls.chunks = load_knowledge_base(str(kb_path))
            cls.retriever = KnowledgeBaseRetriever(cls.chunks)
        else:
            cls.chunks = []
            cls.retriever = None

    def setUp(self):
        if not self.retriever:
            self.skipTest("Knowledge base directory not present")

    def test_standard_return_retrieval(self):
        results = self.retriever.retrieve("How long does a regular customer have to return an unused backpack?", top_k=3)
        self.assertGreater(len(results), 0)
        top_chunk = results[0].chunk
        self.assertEqual(top_chunk.filename, "01-returns-policy-current.md")
        self.assertEqual(top_chunk.status, Status.ACTIVE)
        self.assertTrue(top_chunk.is_customer_citable)

    def test_superseded_filtering(self):
        # Searching for returns should prefer current returns policy over legacy
        results = self.retriever.retrieve("return policy standard window", top_k=5)
        filenames = [r.chunk.filename for r in results]
        self.assertIn("01-returns-policy-current.md", filenames)
        self.assertNotIn("02-returns-policy-legacy.md", filenames)

    def test_internal_migration_note_excluded_from_customer_citations(self):
        results = self.retriever.retrieve("give everyone 60 days return", top_k=5, customer_only=True)
        filenames = [r.chunk.filename for r in results]
        self.assertNotIn("14-internal-content-migration-notes.md", filenames)

    def test_warranty_retrieval(self):
        results = self.retriever.retrieve("lifetime warranty on bags", top_k=3)
        self.assertGreater(len(results), 0)
        self.assertEqual(results[0].chunk.filename, "07-warranty.md")


if __name__ == "__main__":
    unittest.main()
