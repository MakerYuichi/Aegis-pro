"""Fixture for the unchecked_optional_attr pattern.

The pattern matcher fires on `foo().bar` — attribute access on a
call result. This module has exactly that shape, with the call
returning Optional[Order] so the chain builder resolves to a real
Optional terminal.

This is the shape the composition test needs. The self.rag case in
incident_service.py exercises the chain builder directly (via a
symbol trace), but it doesn't trigger the pattern matcher because
`self.rag.search(...)` is an attribute on a name, not on a call.
"""
from typing import Optional


class Order:
    def __init__(self, total: float):
        self.total = total


def fetch_order(order_id: str) -> Optional[Order]:
    """Return an Order, or None if the id doesn't resolve."""
    if order_id == "missing":
        return None
    return Order(total=0.0)


async def charge(order_id: str) -> float:
    """Charge the order. Crashes if the order doesn't exist."""
    return fetch_order(order_id).total
