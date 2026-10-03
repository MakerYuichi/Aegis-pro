"""The terminal type. A concrete class — the chain stops here."""
from dataclasses import dataclass


@dataclass
class Order:
    id: str
    total: float
