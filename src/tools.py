"""
Order Lookup Tool for Aster & Row Support Agent.
Loads orders.json, normalizes order IDs, scrubs PII/internal notes,
enforces status precedence, and returns typed SafeOrderResult DTOs.
"""

import json
import re
from pathlib import Path
from typing import Optional, Dict, Any, List
from src.contracts import SafeOrderResult, OrderItem


def normalize_order_id(order_id_input: str) -> Optional[str]:
    """
    Normalizes order ID input: strips whitespace, converts to uppercase.
    Validates against pattern ^ORD-\\d+$.
    """
    if not order_id_input:
        return None
    
    cleaned = str(order_id_input).strip().upper()
    if re.match(r"^ORD-\d+$", cleaned):
        return cleaned
    return None


class OrderLookupTool:
    def __init__(self, data_path: str = "data/orders.json"):
        self.data_path = Path(data_path)
        self.orders: Dict[str, Dict[str, Any]] = {}
        self.snapshot_at: Optional[str] = None
        self._load_data()

    def _load_data(self):
        if not self.data_path.exists():
            return
        with open(self.data_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.snapshot_at = data.get("snapshot_at")
        orders_list = data.get("orders", [])
        for ord_rec in orders_list:
            oid = ord_rec.get("order_id")
            if oid:
                self.orders[oid.upper()] = ord_rec

    def lookup(self, raw_order_id: str) -> Optional[SafeOrderResult]:
        """
        Performs safe lookup for order ID.
        Returns SafeOrderResult if found, or None if unknown/invalid.
        """
        norm_id = normalize_order_id(raw_order_id)
        if not norm_id or norm_id not in self.orders:
            return None

        record = self.orders[norm_id]
        status = str(record.get("status", "unknown")).lower()

        # Parse items into safe OrderItem DTOs
        raw_items = record.get("items", [])
        safe_items: List[OrderItem] = []
        for item in raw_items:
            safe_items.append(
                OrderItem(
                    name=item.get("name", "Item"),
                    quantity=int(item.get("quantity", 1)),
                    final_sale=bool(item.get("final_sale", False))
                )
            )

        # Enforce Status Precedence Rules
        # Stale delivery estimates on cancelled or returned orders must be forced to None
        delivery_est = record.get("estimated_delivery")
        carrier = record.get("carrier")
        tracking_num = record.get("tracking_number")

        if status in ("cancelled", "returned"):
            delivery_est = None

        return SafeOrderResult(
            order_id=norm_id,
            status=status,
            items=safe_items,
            placed_at=record.get("placed_at"),
            delivered_at=record.get("delivered_at"),
            carrier=carrier,
            tracking_number=tracking_num,
            delivery_estimate=delivery_est,
            customer_safe_message=record.get("customer_safe_message")
        )
