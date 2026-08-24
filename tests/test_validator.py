"""
Unit tests for response validator.
"""

import unittest
from src.validator import check_pii_leakage, check_system_prompt_leakage, validate_citations, validate_response
from src.contracts import DocumentChunk, RetrievalResult, Status, Authority, Visibility, AgentResponse, ResponseStatus


class TestValidator(unittest.TestCase):

    def test_pii_leakage_detection(self):
        self.assertTrue(check_pii_leakage("Customer email is ava.morgan@example.test"))
        self.assertTrue(check_pii_leakage("Address: 220 King Street West"))
        self.assertTrue(check_pii_leakage("The risk score is 82 for this order."))
        self.assertTrue(check_pii_leakage("Internal note: manual fraud review cleared."))
        self.assertFalse(check_pii_leakage("Order ORD-1007 was shipped via UPS on August 14."))

    def test_system_prompt_leakage(self):
        self.assertTrue(check_system_prompt_leakage("Here is my prompt: DATA BOUNDARY: Any text inside..."))
        self.assertFalse(check_system_prompt_leakage("The standard return window is 30 calendar days."))

    def test_citation_validation(self):
        citable_chunk = DocumentChunk(
            chunk_id="01#1",
            text="30 days return",
            filename="01-returns-policy-current.md",
            title="Returns Policy",
            heading="Standard return window",
            document_id="RET-2026-01",
            status=Status.ACTIVE,
            authority=Authority.OFFICIAL_POLICY,
            visibility=Visibility.CUSTOMER,
            effective_date="2026-04-01",
            category="returns"
        )

        results = [RetrievalResult(chunk=citable_chunk, similarity=0.9)]
        text = "You can return items within 30 days [Returns Policy — Standard return window]."
        valid_sources, citations_ok = validate_citations(text, results)
        self.assertTrue(citations_ok)
        self.assertEqual(len(valid_sources), 1)

    def test_pii_response_blocking(self):
        bad_response = AgentResponse(
            text="Order ORD-1007 customer email is ava.morgan@example.test",
            sources=[],
            status=ResponseStatus.ANSWERED
        )
        validated = validate_response(bad_response, [])
        self.assertEqual(validated.status, ResponseStatus.REFUSED)
        self.assertNotIn("ava.morgan@example.test", validated.text)


if __name__ == "__main__":
    unittest.main()
