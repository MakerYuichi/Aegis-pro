from sqlalchemy import text
from src.database import get_db_session
from loguru import logger
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import threading

# ---------------------------------------------------------------------------
# Process-wide singleton
# ---------------------------------------------------------------------------
#
# RAGService.__init__ loads SentenceTransformer('all-MiniLM-L6-v2'), which
# takes seconds on a cold cache. The class is constructed from seven call
# sites today (main.py lifespan, three Slack handlers, one webhook handler,
# two autofix callbacks), and prior to this singleton each one paid that
# cost independently — once per request in the Slack and webhook paths.
#
# The accessor below makes the model load exactly once per process. Call
# sites don't change; they construct IncidentService(), which now calls
# get_rag_service() instead of RAGService().
#
# Caveat for multi-worker deployments: each Uvicorn/Gunicorn worker process
# has its own memory, so N workers still load the model N times. That's
# expected. There's no in-process trick that shares memory across OS
# processes; the alternative is a shared inference service, which is a
# larger change and not this PR's scope.

_rag_instance = None
_rag_lock = threading.Lock()


def get_rag_service() -> "RAGService":
    """
    Return the process-wide RAGService singleton, constructing it on
    first call.

    Thread-safe via _rag_lock. The lock is not strictly needed today
    because the app loads RAG eagerly at startup, so first construction
    happens before any request can race it. But that safety is an
    implicit property of the startup sequence, not a guarantee the code
    enforces. A lock costs nothing and makes the singleton correct
    regardless of how future code calls it.
    """
    global _rag_instance
    if _rag_instance is None:
        with _rag_lock:
            if _rag_instance is None:
                _rag_instance = RAGService()
    return _rag_instance


def _reset_rag_singleton():
    """
    Drop the cached instance so the next get_rag_service() call
    constructs a fresh RAGService.

    Test-only. Do NOT call from production code — every call forces a
    model reload, which is the exact cost this singleton exists to
    avoid.

    Lives here, next to the module-level state it resets, so the reset
    logic doesn't reach into this module from another file.
    """
    global _rag_instance
    with _rag_lock:
        _rag_instance = None


class RAGService:
    def __init__(self):
        self.model = None
        self.use_embeddings = False
        self.executor = ThreadPoolExecutor(max_workers=1)
        
        try:
            from sentence_transformers import SentenceTransformer
            logger.info("🔄 Loading sentence-transformers model...")
            self.model = SentenceTransformer('all-MiniLM-L6-v2')
            self.use_embeddings = True
            logger.info("✅ RAG service initialized with sentence-transformers")
        except Exception as e:
            logger.warning(f"⚠️ Could not load embedding model: {e}")
            logger.info("✅ RAG service initialized in text-search mode")
    
    async def store_incident(self, incident_data: dict):
        """Store incident with embedding for future retrieval"""
        if self.use_embeddings and self.model:
            try:
                loop = asyncio.get_event_loop()
                text_to_embed = f"{incident_data.get('title', '')} {incident_data.get('description', '')} {incident_data.get('stack_trace', '')}"
                embedding = await loop.run_in_executor(
                    self.executor,
                    self.model.encode,
                    text_to_embed
                )
                
                # Convert to list and then to string for PostgreSQL vector
                embedding_list = embedding.tolist()
                embedding_str = '[' + ','.join(str(x) for x in embedding_list) + ']'
                
                async with get_db_session() as session:
                    await session.execute(
                        text("""
                            UPDATE incidents 
                            SET embedding = :embedding 
                            WHERE incident_id = :incident_id
                        """),
                        {
                            "embedding": embedding_str,
                            "incident_id": incident_data['incident_id']
                        }
                    )
                    await session.commit()
                    logger.info(f"✅ Stored embedding for incident {incident_data['incident_id']}")
            except Exception as e:
                logger.error(f"Error storing embedding: {e}")
        else:
            logger.info(f"📝 Incident {incident_data.get('incident_id', 'unknown')} stored")
    
            
    async def store_outcome(self, outcome_data: dict):
        """
        Store a fix outcome (human approve/reject on an auto-generated
        fix) with an embedding so future incidents can retrieve it as
        a few-shot example.

        Embedding text is built from root_cause + suggested_fix +
        stack_context — the same shape used for incidents.embedding —
        so a live incident's vector and a stored outcome's vector are
        comparable. Same encoder (all-MiniLM-L6-v2, 384 dims).

        Expected keys in outcome_data:
            incident_id, service_name, repo_name (opt), fix_diff (opt),
            verification_passed (opt), verification_reason (opt),
            human_decision, human_reason (opt),
            root_cause (opt), suggested_fix (opt), stack_context (opt)

        Failure mode: log and continue. A failure to store an outcome
        must not turn a successful human approve/reject into an error
        for the caller. Same shape as #73's fix.
        """
        incident_id = outcome_data.get("incident_id")
        if not incident_id:
            logger.warning("store_outcome: missing incident_id, skipping")
            return

        embedding_str = None
        if self.use_embeddings and self.model:
            try:
                text_to_embed = self._outcome_embedding_text(outcome_data)
                loop = asyncio.get_event_loop()
                embedding = await loop.run_in_executor(
                    self.executor,
                    self.model.encode,
                    text_to_embed,
                )
                embedding_list = embedding.tolist()
                embedding_str = '[' + ','.join(str(x) for x in embedding_list) + ']'
            except Exception as e:
                logger.error(f"Error computing outcome embedding: {e}")
                embedding_str = None

        try:
            async with get_db_session() as session:
                await session.execute(
                    text("""
                        INSERT INTO fix_outcomes (
                            incident_id, service_name, repo_name,
                            fix_diff, verification_passed, verification_reason,
                            human_decision, human_reason,
                            root_cause, suggested_fix, stack_context,
                            embedding
                        ) VALUES (
                            :incident_id, :service_name, :repo_name,
                            :fix_diff, :verification_passed, :verification_reason,
                            :human_decision, :human_reason,
                            :root_cause, :suggested_fix, :stack_context,
                            :embedding
                        )
                    """),
                    {
                        "incident_id": incident_id,
                        "service_name": outcome_data.get("service_name") or "unknown",
                        "repo_name": outcome_data.get("repo_name"),
                        "fix_diff": outcome_data.get("fix_diff"),
                        "verification_passed": outcome_data.get("verification_passed"),
                        "verification_reason": outcome_data.get("verification_reason"),
                        "human_decision": outcome_data["human_decision"],
                        "human_reason": outcome_data.get("human_reason"),
                        "root_cause": outcome_data.get("root_cause"),
                        "suggested_fix": outcome_data.get("suggested_fix"),
                        "stack_context": outcome_data.get("stack_context"),
                        "embedding": embedding_str,
                    },
                )
                await session.commit()
                logger.info(
                    f"✅ Stored {outcome_data['human_decision']} outcome "
                    f"for incident {incident_id}"
                )
        except Exception as e:
            logger.error(f"Error storing outcome: {e}")

    @staticmethod
    def _outcome_embedding_text(outcome_data: dict) -> str:
        """
        Build the text the outcome embedding is computed from.

        Same shape as the incident embedding input (title + description
        + stack_trace) — here, root_cause + suggested_fix +
        stack_context. The two pipelines encode semantically similar
        text, so cosine similarity between a live incident and a past
        outcome is meaningful.
        """
        return " ".join(filter(None, [
            outcome_data.get("root_cause") or "",
            outcome_data.get("suggested_fix") or "",
            outcome_data.get("stack_context") or "",
        ]))
    
    async def search_similar(self, query: str, limit: int = 3) -> list:
        """Search for similar past incidents"""
        try:
            if self.use_embeddings and self.model:
                try:
                    loop = asyncio.get_event_loop()
                    query_embedding = await loop.run_in_executor(
                        self.executor,
                        self.model.encode,
                        query
                    )
                    
                    # Convert to list and then to string for PostgreSQL vector
                    embedding_list = query_embedding.tolist()
                    embedding_str = '[' + ','.join(str(x) for x in embedding_list) + ']'
                    
                    async with get_db_session() as session:
                        result = await session.execute(
                            text("""
                                SELECT 
                                    incident_id,
                                    title,
                                    description,
                                    root_cause,
                                    suggested_fix,
                                    rollback_command,
                                    severity,
                                    1 - (embedding <=> :embedding) as similarity
                                FROM incidents
                                WHERE embedding IS NOT NULL
                                ORDER BY embedding <=> :embedding
                                LIMIT :limit
                            """),
                            {
                                "embedding": embedding_str,
                                "limit": limit
                            }
                        )
                        
                        rows = result.fetchall()
                        similar = [
                            {
                                "incident_id": row[0],
                                "title": row[1],
                                "description": row[2][:200] + "..." if row[2] and len(row[2]) > 200 else row[2],
                                "root_cause": row[3],
                                "suggested_fix": row[4],
                                "rollback_command": row[5],
                                "severity": row[6],
                                "similarity": float(row[7]) if row[7] else 0
                            }
                            for row in rows
                        ]
                        
                        if similar:
                            logger.info(f"Found {len(similar)} similar incidents via embeddings")
                        return similar
                except Exception as e:
                    logger.error(f"Embedding search failed: {e}")
                    return await self._text_search(query, limit)
            else:
                return await self._text_search(query, limit)
                
        except Exception as e:
            logger.error(f"Error searching: {e}")
            return await self._text_search(query, limit)
        
    
    async def search_similar_outcomes(
        self,
        query: str,
        service_name: str,
        repo_name: str | None = None,
        limit: int = 3,
    ) -> list:
        """
        Retrieve past fix outcomes similar to a live incident, for use
        as few-shot examples.

        Scoping:
            1. Same service, ordered by vector similarity
            2. If fewer than `limit` results, fall back to same repo
            3. No global scope — cross-service retrieval would leak
               one customer's patterns into another's prompt in a
               multi-tenant deployment

        Only returns rows where human_decision is set (approved or
        rejected). Outcomes with a null decision are incomplete cases,
        not clean signals.

        Failure mode: log and continue with whatever's retrievable.
        Returns [] if nothing matches or if embeddings aren't available
        and the text search also finds nothing.
        """
        if not query or not service_name:
            return []

        try:
            results = await self._search_outcomes_by_service(
                query, service_name, limit
            )

            if len(results) < limit and repo_name:
                seen_ids = {r["id"] for r in results}
                fallback = await self._search_outcomes_by_repo(
                    query, repo_name, limit, exclude_ids=seen_ids
                )
                results.extend(fallback)

            return results[:limit]
        except Exception as e:
            logger.error(f"Error searching outcomes: {e}")
            return []

    async def _search_outcomes_by_service(
        self, query: str, service_name: str, limit: int
    ) -> list:
        return await self._search_outcomes(
            query, "service_name = :scope", {"scope": service_name}, limit
        )

    async def _search_outcomes_by_repo(
        self, query: str, repo_name: str, limit: int, exclude_ids: set
    ) -> list:
        results = await self._search_outcomes(
            query, "repo_name = :scope", {"scope": repo_name}, limit
        )
        return [r for r in results if r["id"] not in exclude_ids]

    async def _search_outcomes(
        self, query: str, scope_clause: str, scope_params: dict, limit: int
    ) -> list:
        """
        Shared retrieval path. If embeddings are available, does vector
        similarity within the scope; otherwise falls back to newest-
        first within the scope. Both paths filter human_decision IS NOT
        NULL.
        """
        embedding_str = None
        if self.use_embeddings and self.model:
            try:
                loop = asyncio.get_event_loop()
                query_embedding = await loop.run_in_executor(
                    self.executor, self.model.encode, query
                )
                embedding_list = query_embedding.tolist()
                embedding_str = '[' + ','.join(str(x) for x in embedding_list) + ']'
            except Exception as e:
                logger.error(f"Outcome embedding failed, falling back to recency: {e}")
                embedding_str = None

        params = dict(scope_params)
        params["limit"] = limit

        if embedding_str:
            params["embedding"] = embedding_str
            sql = f"""
                SELECT id, incident_id, service_name, repo_name,
                       root_cause, suggested_fix, fix_diff,
                       verification_passed, human_decision, human_reason,
                       1 - (embedding <=> :embedding) AS similarity
                FROM fix_outcomes
                WHERE {scope_clause}
                  AND human_decision IS NOT NULL
                  AND embedding IS NOT NULL
                ORDER BY embedding <=> :embedding
                LIMIT :limit
            """
        else:
            sql = f"""
                SELECT id, incident_id, service_name, repo_name,
                       root_cause, suggested_fix, fix_diff,
                       verification_passed, human_decision, human_reason,
                       0.5 AS similarity
                FROM fix_outcomes
                WHERE {scope_clause}
                  AND human_decision IS NOT NULL
                ORDER BY created_at DESC
                LIMIT :limit
            """

        async with get_db_session() as session:
            result = await session.execute(text(sql), params)
            rows = result.fetchall()

        return [
            {
                "id": row[0],
                "incident_id": row[1],
                "service_name": row[2],
                "repo_name": row[3],
                "root_cause": row[4],
                "suggested_fix": row[5],
                "fix_diff": row[6],
                "verification_passed": row[7],
                "human_decision": row[8],
                "human_reason": row[9],
                "similarity": float(row[10]) if row[10] is not None else 0.0,
            }
            for row in rows
        ]
    
    
    async def _text_search(self, query: str, limit: int = 3) -> list:
        """Fallback text-based search"""
        try:
            keywords = query.lower().split()
            stopwords = {'a', 'an', 'the', 'to', 'for', 'of', 'with', 'on', 'at', 'from', 'by', 'in', 'is', 'it', 'was', 'were', 'and', 'or', 'but'}
            keywords = [k for k in keywords if k not in stopwords and len(k) > 2]
            
            if not keywords:
                return []
            
            conditions = []
            params = {}
            for i, kw in enumerate(keywords):
                conditions.append(f"(title ILIKE :kw{i} OR description ILIKE :kw{i} OR stack_trace ILIKE :kw{i})")
                params[f"kw{i}"] = f"%{kw}%"
            
            where_clause = " OR ".join(conditions)
            params["limit"] = limit
            
            async with get_db_session() as session:
                result = await session.execute(
                    text(f"""
                        SELECT 
                            incident_id,
                            title,
                            description,
                            root_cause,
                            suggested_fix,
                            rollback_command,
                            severity,
                            created_at
                        FROM incidents
                        WHERE {where_clause}
                        ORDER BY created_at DESC
                        LIMIT :limit
                    """),
                    params
                )
                
                rows = result.fetchall()
                return [
                    {
                        "incident_id": row[0],
                        "title": row[1],
                        "description": row[2][:200] + "..." if row[2] and len(row[2]) > 200 else row[2],
                        "root_cause": row[3],
                        "suggested_fix": row[4],
                        "rollback_command": row[5],
                        "severity": row[6],
                        "similarity": 0.5
                    }
                    for row in rows
                ]
        except Exception as e:
            logger.error(f"Error in text search: {e}")
            return []
    
    async def generate_context_prompt(self, query: str) -> str:
        """Generate a context prompt from similar incidents for LLM"""
        similar = await self.search_similar(query, limit=3)
        
        if not similar:
            return ""
        
        context = "\n**📚 Similar past incidents found:**\n"
        for i, inc in enumerate(similar, 1):
            similarity_text = f" (similarity: {inc['similarity']:.2f})" if inc.get('similarity') else ""
            context += f"""
{i}. Incident {inc['incident_id']}{similarity_text}
   - Title: {inc['title']}
   - Root Cause: {inc['root_cause'][:200] if inc.get('root_cause') else 'Unknown'}
   - Suggested Fix: {inc['suggested_fix'][:200] if inc.get('suggested_fix') else 'Not available'}
"""
        
        return context
