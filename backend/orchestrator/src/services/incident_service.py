from sqlalchemy import text
from datetime import datetime
import uuid
import json
from loguru import logger

from src.database import get_db
from src.services.llm_service import LLMService
from src.services.rag_service import RAGService

class IncidentService:
    def __init__(self):
        self.llm = LLMService()
        self.rag = RAGService()
        logger.info("✅ IncidentService initialized with RAG")
    
    async def declare_incident(self, service_name: str, message: str, stack_trace: str = None) -> dict:
        """Declare a new incident with RAG context"""
        incident_id = f"INC-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
        
        logger.info(f"🚨 Declaring incident: {incident_id} for service: {service_name}")
        
        service = await self.get_service(service_name)
        if not service:
            return {
                "error": f"Service '{service_name}' not found",
                "available_services": await self.list_services()
            }
        
        stack_analysis = None
        if stack_trace:
            stack_analysis = self._parse_stack_trace(stack_trace)
        
        blast_radius = await self.calculate_blast_radius(
            service_name=service_name,
            dependencies=service.get("dependencies", [])
        )
        
        # RAG: Search for similar past incidents
        rag_context = await self.rag.generate_context_prompt(message)
        rag_used = bool(rag_context)
        if rag_used:
            logger.info(f"📚 Found similar past incidents for context!")
        else:
            logger.info("📚 No similar past incidents found yet")
        
        # Use LLM with RAG context
        analysis = await self.llm.analyze_incident(
            service_name=service_name,
            message=message,
            stack_analysis=stack_analysis,
            blast_radius=blast_radius,
            rag_context=rag_context
        )
        
        # Convert dict to JSON string for PostgreSQL
        extra_metadata_json = json.dumps({"rag_context_used": rag_used})
        affected_services_json = json.dumps(blast_radius.get("affected", []))
        
        incident_data = {
            "incident_id": incident_id,
            "service_name": service_name,
            "severity": analysis.get("severity", "P1"),
            "status": "active",
            "title": analysis.get("title", f"{service_name} incident"),
            "description": message,
            "stack_trace": stack_trace,
            "exception_type": stack_analysis.get("exception_type") if stack_analysis else None,
            "file_path": stack_analysis.get("file_path") if stack_analysis else None,
            "line_number": stack_analysis.get("line_number") if stack_analysis else None,
            "root_cause": analysis.get("root_cause", ""),
            "suggested_fix": analysis.get("suggested_fix", ""),
            "rollback_command": analysis.get("rollback_command", ""),
            "confidence_score": analysis.get("confidence", 0.7),
            "declared_at": datetime.utcnow(),
            "extra_metadata": extra_metadata_json,
            "affected_services": affected_services_json
        }
        
        await self.save_incident(incident_data)
        
        # Store for future RAG searches
        await self.rag.store_incident(incident_data)
        
        return {
            "incident_id": incident_id,
            "service": service_name,
            "severity": analysis.get("severity"),
            "title": analysis.get("title"),
            "on_call": service.get("on_call", []),
            "root_cause": analysis.get("root_cause"),
            "suggested_fix": analysis.get("suggested_fix"),
            "rollback_command": analysis.get("rollback_command"),
            "confidence": analysis.get("confidence"),
            "blast_radius": blast_radius,
            "rag_context_used": rag_used,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    async def get_service(self, service_name: str) -> dict:
        """Get service from catalog"""
        try:
            session = await get_db()
            async with session:
                result = await session.execute(
                    text("SELECT * FROM services WHERE name = :name"),
                    {"name": service_name}
                )
                row = result.fetchone()
                if row:
                    return dict(row._mapping)
                return None
        except Exception as e:
            logger.error(f"Error getting service: {e}")
            return self._mock_service(service_name)
    
    async def list_services(self) -> list:
        """List all services"""
        try:
            session = await get_db()
            async with session:
                result = await session.execute(text("SELECT name FROM services ORDER BY name"))
                return [row[0] for row in result.fetchall()]
        except Exception as e:
            logger.error(f"Error listing services: {e}")
            return ["payment-api", "auth", "ledger", "refund", "fraud", "notification", "user", "database"]
    
    async def save_incident(self, incident_data: dict):
        """Save incident to database"""
        try:
            session = await get_db()
            async with session:
                # Use the JSON strings directly - PostgreSQL will handle them as text
                await session.execute(
                    text("""
                        INSERT INTO incidents (
                            incident_id, service_name, severity, status, title, description,
                            stack_trace, exception_type, file_path, line_number,
                            root_cause, suggested_fix, rollback_command, confidence_score,
                            declared_at, extra_metadata, affected_services
                        ) VALUES (
                            :incident_id, :service_name, :severity, :status, :title, :description,
                            :stack_trace, :exception_type, :file_path, :line_number,
                            :root_cause, :suggested_fix, :rollback_command, :confidence_score,
                            :declared_at, :extra_metadata, :affected_services
                        )
                    """),
                    incident_data
                )
                await session.commit()
                logger.info(f"✅ Incident {incident_data['incident_id']} saved")
        except Exception as e:
            logger.error(f"Error saving incident: {e}")
    
    async def get_incident(self, incident_id: str) -> dict:
        """Get incident by ID"""
        try:
            session = await get_db()
            async with session:
                result = await session.execute(
                    text("SELECT * FROM incidents WHERE incident_id = :incident_id"),
                    {"incident_id": incident_id}
                )
                row = result.fetchone()
                if row:
                    return dict(row._mapping)
                return None
        except Exception as e:
            logger.error(f"Error getting incident: {e}")
            return None
    
    async def get_all_incidents(self, limit: int = 50) -> list:
        """Get all incidents"""
        try:
            session = await get_db()
            async with session:
                result = await session.execute(
                    text("""
                        SELECT incident_id, service_name, severity, status, title, 
                               root_cause, suggested_fix, confidence_score, declared_at
                        FROM incidents 
                        ORDER BY declared_at DESC 
                        LIMIT :limit
                    """),
                    {"limit": limit}
                )
                rows = result.fetchall()
                return [dict(row._mapping) for row in rows]
        except Exception as e:
            logger.error(f"Error getting incidents: {e}")
            return []
    
    async def calculate_blast_radius(self, service_name: str, dependencies: list) -> dict:
        """Calculate blast radius"""
        affected = [service_name]
        
        for dep in dependencies:
            affected.append(dep)
            service = await self.get_service(dep)
            if service and service.get("dependencies"):
                affected.extend(service["dependencies"])
        
        affected = list(set(affected))
        
        severity = "CRITICAL" if len(affected) > 5 else "HIGH" if len(affected) > 2 else "MEDIUM"
        
        return {
            "root": service_name,
            "affected": affected,
            "count": len(affected),
            "severity": severity
        }
    
    async def rollback(self, incident_id: str) -> dict:
        """Execute rollback (mock)"""
        incident = await self.get_incident(incident_id)
        if not incident:
            return {"error": "Incident not found"}
        
        try:
            session = await get_db()
            async with session:
                await session.execute(
                    text("UPDATE incidents SET status = 'resolved', resolved_at = NOW() WHERE incident_id = :incident_id"),
                    {"incident_id": incident_id}
                )
                await session.commit()
        except Exception as e:
            logger.error(f"Error updating incident: {e}")
        
        return {
            "incident_id": incident_id,
            "status": "rollback_initiated",
            "rollback_command": incident.get("rollback_command", "kubectl rollout undo deployment"),
            "estimated_time": "2 minutes",
            "mock": True
        }
    
    async def seed_services(self) -> dict:
        """Seed demo services"""
        try:
            session = await get_db()
            async with session:
                await session.execute(text("DELETE FROM services"))
                
                services = [
                    ("payment-api", "Payment processing", "payment-service", '["@rahul", "@priya"]', '["auth", "ledger"]', True),
                    ("auth", "Authentication", "auth-service", '["@amit"]', '[]', True),
                    ("ledger", "Transaction ledger", "ledger-service", '["@sneha"]', '["database"]', True),
                    ("refund", "Refund processing", "refund-service", '["@ananya"]', '["payment-api"]', False),
                    ("fraud", "Fraud detection", "fraud-service", '["@raj"]', '["payment-api"]', False),
                    ("notification", "Notifications", "notification-service", '["@kavya"]', '["user"]', False),
                    ("user", "User management", "user-service", '["@arjun"]', '[]', False),
                    ("database", "Database ops", "database-service", '["@shreya"]', '[]', True),
                ]
                
                for service in services:
                    await session.execute(
                        text("""
                            INSERT INTO services (name, description, repo_name, on_call, dependencies, is_critical)
                            VALUES (:name, :description, :repo_name, :on_call, :dependencies, :is_critical)
                        """),
                        {
                            "name": service[0],
                            "description": service[1],
                            "repo_name": service[2],
                            "on_call": service[3],
                            "dependencies": service[4],
                            "is_critical": service[5]
                        }
                    )
                
                await session.commit()
                return {"status": "seeded", "count": len(services)}
        except Exception as e:
            logger.error(f"Error seeding services: {e}")
            return {"status": "error", "message": str(e)}
    
    def _parse_stack_trace(self, stack_trace: str) -> dict:
        """Parse stack trace"""
        import re
        
        exception_pattern = r"([A-Za-z]+Exception|Error):"
        exception_match = re.search(exception_pattern, stack_trace)
        
        file_pattern = r"at\s+[\w.]+\.(\w+)\((\w+\.java):(\d+)\)"
        file_match = re.search(file_pattern, stack_trace)
        
        if not file_match:
            file_pattern = r'File "([^"]+)", line (\d+)'
            file_match = re.search(file_pattern, stack_trace)
            if file_match:
                return {
                    "exception_type": exception_match.group(1) if exception_match else "Exception",
                    "file_path": file_match.group(1),
                    "line_number": int(file_match.group(2)),
                    "full_trace": stack_trace[:500]
                }
        
        return {
            "exception_type": exception_match.group(1) if exception_match else "Exception",
            "file_path": file_match.group(2) if file_match else None,
            "line_number": int(file_match.group(3)) if file_match and len(file_match.groups()) >= 3 else None,
            "full_trace": stack_trace[:500]
        }
    
    def _mock_service(self, service_name: str) -> dict:
        """Mock service when DB not available"""
        services = {
            "payment-api": {"name": "payment-api", "on_call": ["@rahul", "@priya"], "dependencies": ["auth", "ledger"]},
            "auth": {"name": "auth", "on_call": ["@amit"], "dependencies": []},
            "ledger": {"name": "ledger", "on_call": ["@sneha"], "dependencies": ["database"]},
            "refund": {"name": "refund", "on_call": ["@ananya"], "dependencies": ["payment-api"]},
            "fraud": {"name": "fraud", "on_call": ["@raj"], "dependencies": ["payment-api"]},
            "notification": {"name": "notification", "on_call": ["@kavya"], "dependencies": ["user"]},
            "user": {"name": "user", "on_call": ["@arjun"], "dependencies": []},
            "database": {"name": "database", "on_call": ["@shreya"], "dependencies": []}
        }
        return services.get(service_name, {"name": service_name, "on_call": [], "dependencies": []})