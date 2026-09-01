from sqlalchemy import text
from src.database import get_db
from loguru import logger
import numpy as np

class RAGService:
    def __init__(self):
        self.model = None
        self.use_embeddings = False
        
        # Try to load sentence-transformers with proper error handling
        try:
            from sentence_transformers import SentenceTransformer
            # Use a lightweight but powerful model
            self.model = SentenceTransformer('all-MiniLM-L6-v2')
            self.use_embeddings = True
            logger.info("✅ RAG service initialized with sentence-transformers (embeddings enabled)")
        except ImportError as e:
            logger.warning(f"⚠️ sentence-transformers not installed: {e}")
            logger.info("✅ RAG service initialized in fallback mode (text-based search)")
        except Exception as e:
            logger.warning(f"⚠️ Could not load embedding model: {e}")
            logger.info("✅ RAG service initialized in fallback mode")
    
    async def store_incident(self, incident_data: dict):
        """Store incident with embedding for future retrieval"""
        if self.use_embeddings and self.model:
            try:
                # Create text for embedding
                text_to_embed = f"{incident_data.get('title', '')} {incident_data.get('description', '')} {incident_data.get('stack_trace', '')}"
                embedding = self.model.encode(text_to_embed).tolist()
                
                async with get_db() as session:
                    await session.execute(
                        text("""
                            UPDATE incidents 
                            SET embedding = :embedding::vector 
                            WHERE incident_id = :incident_id
                        """),
                        {
                            "embedding": embedding,
                            "incident_id": incident_data['incident_id']
                        }
                    )
                    await session.commit()
                    logger.info(f"✅ Stored embedding for incident {incident_data['incident_id']}")
            except Exception as e:
                logger.error(f"Error storing embedding: {e}")
        else:
            logger.info(f"📝 Incident {incident_data.get('incident_id', 'unknown')} stored (text-search mode)")
    
    async def search_similar(self, query: str, limit: int = 3) -> list:
        """Search for similar past incidents using embeddings or text search"""
        try:
            async with get_db() as session:
                if self.use_embeddings and self.model:
                    # Vector similarity search
                    query_embedding = self.model.encode(query).tolist()
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
                                1 - (embedding <=> :query_embedding::vector) as similarity
                            FROM incidents
                            WHERE embedding IS NOT NULL
                            ORDER BY embedding <=> :query_embedding::vector
                            LIMIT :limit
                        """),
                        {
                            "query_embedding": query_embedding,
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
                        logger.info(f"Found {len(similar)} similar incidents via embeddings (best: {similar[0]['similarity']:.2f})")
                    return similar
                else:
                    # Fallback: text-based search
                    return await self._text_search(query, limit)
                
        except Exception as e:
            logger.error(f"Error searching similar incidents: {e}")
            return await self._text_search(query, limit)
    
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
            
            async with get_db() as session:
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
                similar = [
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
                
                if similar:
                    logger.info(f"Found {len(similar)} similar incidents via text search (fallback)")
                return similar
                
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
