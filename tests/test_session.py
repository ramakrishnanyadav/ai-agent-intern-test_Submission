"""
Unit tests for session management and query rewriting.
"""

import unittest
from src.session import SessionManager, extract_order_id_from_text


class TestSessionManager(unittest.TestCase):

    def setUp(self):
        self.mgr = SessionManager()

    def test_extract_order_id(self):
        self.assertEqual(extract_order_id_from_text("Where is ORD-1007?"), "ORD-1007")
        self.assertEqual(extract_order_id_from_text("check ord-1004 please"), "ORD-1004")
        self.assertIsNone(extract_order_id_from_text("What is your return policy?"))

    def test_canada_multiturn_query_rewrite(self):
        sess = self.mgr.get_or_create_session("sess_1")
        
        # Turn 1
        q1, order_id_1, amb_1 = self.mgr.rewrite_query(sess, "Do you ship internationally?")
        self.assertEqual(sess.last_topic, "shipping")
        self.mgr.record_turn(sess, "Do you ship internationally?", "Yes, we ship to select international locations.")

        # Turn 2
        q2, order_id_2, amb_2 = self.mgr.rewrite_query(sess, "What about Canada, and how long does it take?")
        self.assertIn("Canada", q2)
        self.assertIn("shipping", q2.lower())

    def test_order_followup_query_rewrite(self):
        sess = self.mgr.get_or_create_session("sess_2")
        
        # Turn 1
        q1, order_id_1, amb_1 = self.mgr.rewrite_query(sess, "Where is ORD-1007?")
        self.assertEqual(order_id_1, "ORD-1007")
        self.mgr.record_turn(sess, "Where is ORD-1007?", "Order ORD-1007 has shipped.", order_id="ORD-1007")

        # Turn 2
        q2, order_id_2, amb_2 = self.mgr.rewrite_query(sess, "When will it arrive?")
        self.assertEqual(order_id_2, "ORD-1007")
        self.assertIn("ORD-1007", q2)

    def test_session_isolation(self):
        sess_a = self.mgr.get_or_create_session("session_A")
        sess_b = self.mgr.get_or_create_session("session_B")

        self.mgr.rewrite_query(sess_a, "Check ORD-1001")
        self.mgr.rewrite_query(sess_b, "Check ORD-1007")

        self.assertEqual(sess_a.last_order_id, "ORD-1001")
        self.assertEqual(sess_b.last_order_id, "ORD-1007")
        self.assertNotEqual(sess_a.last_order_id, sess_b.last_order_id)


if __name__ == "__main__":
    unittest.main()
