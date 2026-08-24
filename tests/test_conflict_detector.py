"""
Standalone unit tests for conflict detector.
"""

import unittest
from pathlib import Path
from src.ingestion import load_knowledge_base
from src.retrieval import KnowledgeBaseRetriever
from src.conflict_detector import normalize_supported_policy_facts, compare_facts


class TestConflictDetector(unittest.TestCase):

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

    def test_breeze_tumbler_conflict_detection(self):
        # Query retrieving both care guide (11) and product card (12)
        results = self.retriever.retrieve("Can I put the entire Breeze Tumbler in the dishwasher?", top_k=5)
        facts = normalize_supported_policy_facts(results)
        self.assertGreater(len(facts), 1)

        conflict = compare_facts(facts)
        self.assertIsNotNone(conflict)
        fact_a, fact_b = conflict
        self.assertEqual(fact_a.product, "Breeze Tumbler")
        self.assertEqual(fact_b.product, "Breeze Tumbler")
        self.assertNotEqual(fact_a.value, fact_b.value)

    def test_no_false_conflict_on_trailplus_vs_standard_returns(self):
        results = self.retriever.retrieve("What is the return window for standard and TrailPlus orders?", top_k=5)
        facts = normalize_supported_policy_facts(results)
        conflict = compare_facts(facts)
        # Standard (30) vs TrailPlus (45) should NOT be flagged as conflict because scopes differ
        self.assertIsNone(conflict)


if __name__ == "__main__":
    unittest.main()
