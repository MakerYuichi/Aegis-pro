"""Fixture repo for read_symbol tests.

Deliberately mirrors the shape of the real incident_service.py
around the #105 case: a class with a self.rag attribute assigned
in __init__ from a function that can return None.
"""
from typing import Optional


def get_rag_service() -> Optional["RagService"]:
    """Return the RAG singleton, or None if the chain failed to init."""
    try:
        return RagService()
    except Exception:
        return None


class RagService:
    def __init__(self):
        self.chain = []

    async def search_similar_outcomes(self, query: str, service_name: str):
        if not self.chain:
            return None
        return {"hits": []}


class IncidentService:
    def __init__(self):
        self.rag = get_rag_service()
        self.timeout = 30

    async def declare_incident(self, service_name: str, message: str):
        outcome = await self.rag.search_similar_outcomes(message, service_name)
        return outcome
