"""The crash site. `order` comes from `fetch_order`, which returns
Optional[Order]. `order.total` is the unchecked attribute access.
"""
from typing import Optional

from payment_chain.order_service import fetch_order


async def charge(order_id: str) -> float:
    order = await fetch_order(order_id)
    return order.total
