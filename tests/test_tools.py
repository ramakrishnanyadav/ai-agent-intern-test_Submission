"""
Unit tests for order lookup tool and PII scrubbing.
"""

import unittest
from pathlib import Path
from src.tools import OrderLookupTool, normalize_order_id
from src.contracts import SafeOrderResult


class TestOrderLookupTool(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        data_path = Path("data/orders.json")
        if data_path.exists():
            cls.tool = OrderLookupTool(str(data_path))
        else:
            cls.tool = None

    def setUp(self):
        if not self.tool:
            self.skipTest("data/orders.json file not present")

    def test_normalize_order_id(self):
        self.assertEqual(normalize_order_id("ord-1007"), "ORD-1007")
        self.assertEqual(normalize_order_id("  ORD-1007  "), "ORD-1007")
        self.assertEqual(normalize_order_id("ORD-1007"), "ORD-1007")
        self.assertIsNone(normalize_order_id("invalid-id"))
        self.assertIsNone(normalize_order_id("1007"))

    def test_valid_order_lookup(self):
        result = self.tool.lookup("ord-1007")
        self.assertIsNotNone(result)
        self.assertIsInstance(result, SafeOrderResult)
        self.assertEqual(result.order_id, "ORD-1007")
        self.assertEqual(result.status, "shipped")
        self.assertEqual(result.carrier, "UPS")
        self.assertEqual(result.delivery_estimate, "2026-08-22")

        # Verify PII fields are NOT present on SafeOrderResult dataclass
        self.assertFalse(hasattr(result, "email"))
        self.assertFalse(hasattr(result, "address"))
        self.assertFalse(hasattr(result, "risk_score"))
        self.assertFalse(hasattr(result, "internal"))

    def test_cancelled_order_stale_eta_forced_to_none(self):
        # ORD-1004 is cancelled in dataset but contains a stale estimated_delivery ("2026-08-16")
        result = self.tool.lookup("ORD-1004")
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "cancelled")
        self.assertIsNone(result.delivery_estimate)

    def test_shipped_order_without_eta(self):
        # ORD-1011 is shipped with Canada Post but has estimated_delivery: null
        result = self.tool.lookup("ORD-1011")
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "shipped")
        self.assertEqual(result.carrier, "Canada Post")
        self.assertIsNone(result.delivery_estimate)

    def test_unknown_order(self):
        result = self.tool.lookup("ORD-9999")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
