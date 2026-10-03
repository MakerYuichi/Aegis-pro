"""The terminal of the chain. `get_by_id` returns Optional[Order]."""
from typing import Optional

from payment_chain.models import Order


async def get_by_id(order_id: str) -> Optional[Order]:
    if order_id == "missing":
        return None
    return Order(id=order_id, total=0.0)
