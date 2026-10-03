"""The middle of the chain. `fetch_order` returns Optional[Order]."""
from typing import Optional

from payment_chain.order_repository import get_by_id
from payment_chain.models import Order


async def fetch_order(order_id: str) -> Optional[Order]:
    return await get_by_id(order_id)
