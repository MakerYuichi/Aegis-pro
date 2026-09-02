from sqlalchemy import text
from datetime import datetime
import uuid
import json
from loguru import logger

from src.database import get_db
from src.services.llm_service import LLMService
from src.services.rag_service import RAGService
from src.services.autofix_service import AutoFixService
from src.config import settings
from src.websocket import manager

class IncidentService:
    def __init__(self):
        self.llm = LLMService()
        self.rag = RAGService()
        logger.info("✅ IncidentService initialized with RAG")
    
    async def declare_incident(self, service_name: str, message: str, stack_trace: str = None, reported_by: str = None) -> dict:
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
        
        # --- Build incident_data FIRST ---
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
        
        # --- GitHub Context (AFTER incident_data is defined) ---
        github_context = {}
        try:
            if service.get("repo_name") and settings.GITHUB_TOKEN:
                from src.services.github_service import GitHubService
                github = GitHubService()
                
                # Get recent PRs
                github_context["recent_prs"] = await github.get_recent_prs(service["repo_name"])
                
                # Get specific blame if we have file and line number
                if stack_analysis and stack_analysis.get("file_path"):
                    logger.info(f"🔍 Getting blame for: {stack_analysis['file_path']}:{stack_analysis.get('line_number', 'unknown')}")
                    blame_info = await github.get_blame_with_pr(
                        service["repo_name"],
                        stack_analysis["file_path"],
                        stack_analysis.get("line_number", 1)
                    )
                    if blame_info:
                        github_context["blame"] = blame_info
                        logger.info(f"✅ Blame found: {blame_info.get('author')} - {blame_info.get('message')[:50]}")
                        if blame_info.get('pr_number'):
                            logger.info(f"🔗 PR #{blame_info.get('pr_number')}: {blame_info.get('pr_title')}")
                    else:
                        logger.warning("⚠️ No blame info found for this file/line")
                
                if github_context:
                    logger.info(f"🔗 GitHub context: {len(github_context.get('recent_prs', []))} PRs found")
                    
                    # Update extra_metadata with GitHub context and reported_by
                    incident_data["extra_metadata"] = json.dumps({
                        "rag_context_used": rag_used,
                        "reported_by": reported_by if reported_by else None,
                        "github": github_context
                    })
        except Exception as e:
            logger.error(f"GitHub integration error: {e}")
            
        # --- Code-Level Diagnosis (Fetch actual code from GitHub) ---
        code_context = {}
        if stack_analysis and stack_analysis.get("file_path") and service.get("repo_name"):
            try:
                from src.services.github_service import GitHubService
                github = GitHubService()
                        
                code_context = await github.get_file_content(
                    repo_name=service["repo_name"],
                    file_path=stack_analysis["file_path"],
                    line_number=stack_analysis.get("line_number", 1)
                )
                        
                if code_context:
                    logger.info(f"✅ Code context fetched: {code_context.get('file_path')}:{code_context.get('line_number')}")
                    # Update the incident_data directly
                    if incident_data.get("extra_metadata"):
                        try:
                            metadata = json.loads(incident_data["extra_metadata"])
                        except:
                            metadata = {}

                    else:
                        metadata = {}
                    metadata["code_context"] = code_context
                    incident_data["extra_metadata"] = json.dumps(metadata)
                        
            except Exception as e:
                logger.error(f"Code context error: {e}")
                
                
         # --- Auto-Fix Generation (with permission check) ---
        if stack_analysis and stack_analysis.get("file_path"):
            try:
                from src.services.autofix_service import AutoFixService
                autofix = AutoFixService()
                fix_result = await autofix.generate_fix({
                    "incident_id": incident_id,
                    "service_name": service_name,
                    "file_path": stack_analysis["file_path"],
                    "line_number": stack_analysis.get("line_number"),
                    "exception_type": stack_analysis.get("exception_type"),
                    "root_cause": analysis.get("root_cause")
                }, require_permission=True)  # Always require permission
                        
                if fix_result and not fix_result.get("error"):
                    # Parse existing metadata
                    existing_metadata = {}
                    if incident_data.get("extra_metadata"):
                        try:
                            existing_metadata = json.loads(incident_data["extra_metadata"])
                        except:
                            pass
                            
                    # Update metadata with auto-fix
                    existing_metadata["auto_fix"] = fix_result
                    incident_data["extra_metadata"] = json.dumps(existing_metadata)
                    logger.info(f"✅ Auto-fix generated for {incident_id} (waiting for approval)")
                else:
                    logger.warning(f"⚠️ Auto-fix failed: {fix_result.get('error')}")
            except Exception as e:
                logger.error(f"Auto-fix error: {e}")
        
        # --- Save incident ---
        await self.save_incident(incident_data)
        
        # --- Store for future RAG searches ---
        await self.rag.store_incident(incident_data)
        
        # --- Broadcast via WebSocket ---
        try:
            await manager.broadcast({
                "type": "new_incident",
                "data": {
                    "incident_id": incident_id,
                    "service_name": service_name,
                    "severity": analysis.get("severity"),
                    "title": analysis.get("title")
                }
            })
        except Exception as e:
            logger.error(f"WebSocket broadcast error: {e}")
                
        # --- Auto-Fix Generation (with permission check) ---
        if stack_analysis and stack_analysis.get("file_path"):
            try:
                autofix = AutoFixService()
                
                # Get existing metadata
                existing_metadata = {}
                if incident_data.get("extra_metadata"):
                    try:
                        existing_metadata = json.loads(incident_data["extra_metadata"])
                    except:
                        pass
                
                # Generate fix
                fix_result = await autofix.generate_fix({
                    "incident_id": incident_id,
                    "service_name": service_name,
                    "file_path": stack_analysis["file_path"],
                    "line_number": stack_analysis.get("line_number"),
                    "exception_type": stack_analysis.get("exception_type"),
                    "root_cause": analysis.get("root_cause")
                }, require_permission=True)
                
                if fix_result and not fix_result.get("error"):
                    existing_metadata["auto_fix"] = fix_result
                    incident_data["extra_metadata"] = json.dumps(existing_metadata)
                    logger.info(f"✅ Auto-fix generated for {incident_id} (waiting for approval)")
                else:
                    logger.warning(f"⚠️ Auto-fix failed: {fix_result.get('error')}")
            except Exception as e:
                logger.error(f"Auto-fix error: {e}")
        
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
        """List all services with full details"""
        try:
            session = await get_db()
            async with session:
                result = await session.execute(
                    text("""
                        SELECT 
                            name, 
                            description, 
                            on_call, 
                            dependencies, 
                            is_critical 
                        FROM services 
                        ORDER BY name
                    """)
                )
                rows = result.fetchall()
                return [
                    {
                        "name": row[0],
                        "description": row[1],
                        "on_call": row[2] if row[2] else [],
                        "dependencies": row[3] if row[3] else [],
                        "is_critical": row[4] if row[4] else False
                    }
                    for row in rows
                ]
        except Exception as e:
            logger.error(f"Error listing services: {e}")
            return self._mock_services_list()
    
    async def save_incident(self, incident_data: dict):
        """Save incident to database"""
        try:
            session = await get_db()
            async with session:
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
                    data = dict(row._mapping)
                    # Parse JSONB fields back to Python objects
                    if data.get('extra_metadata') and isinstance(data['extra_metadata'], str):
                        try:
                            data['extra_metadata'] = json.loads(data['extra_metadata'])
                        except:
                            pass
                    if data.get('affected_services') and isinstance(data['affected_services'], str):
                        try:
                            data['affected_services'] = json.loads(data['affected_services'])
                        except:
                            pass
                    return data
                return None
        except Exception as e:
            logger.error(f"Error getting incident: {e}")
            return None
    
    async def get_all_incidents(self, limit: int = 50) -> list:
        """Get all incidents with proper parsing"""
        try:
            session = await get_db()
            async with session:
                result = await session.execute(
                    text("""
                        SELECT 
                            incident_id, 
                            service_name, 
                            severity, 
                            status, 
                            title,
                            description,
                            root_cause,
                            suggested_fix,
                            rollback_command,
                            confidence_score,
                            affected_services,
                            declared_at
                        FROM incidents 
                        ORDER BY declared_at DESC 
                        LIMIT :limit
                    """),
                    {"limit": limit}
                )
                rows = result.fetchall()
                incidents = []
                for row in rows:
                    incident = {
                        "incident_id": row[0],
                        "service_name": row[1],
                        "severity": row[2],
                        "status": row[3],
                        "title": row[4],
                        "description": row[5],
                        "root_cause": row[6],
                        "suggested_fix": row[7],
                        "rollback_command": row[8],
                        "confidence_score": row[9],
                        "declared_at": row[11]
                    }
                    if row[10]:
                        if isinstance(row[10], str):
                            try:
                                incident["affected_services"] = json.loads(row[10])
                            except:
                                incident["affected_services"] = []
                        elif isinstance(row[10], list):
                            incident["affected_services"] = row[10]
                        else:
                            incident["affected_services"] = []
                    else:
                        incident["affected_services"] = []
                    incidents.append(incident)
                return incidents
        except Exception as e:
            logger.error(f"Error getting incidents: {e}")
            return []
    
    async def calculate_blast_radius(self, service_name: str, dependencies: list) -> dict:
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
        try:
            session = await get_db()
            async with session:
                await session.execute(text("DELETE FROM services"))
                
                services = [
                    ("payment-api", "Payment processing", "fastapi", '["@rahul", "@priya"]', '["auth", "ledger"]', True),
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
        """Parse stack trace - handles multiple formats"""
        import re
        
        result = {
            "exception_type": None,
            "file_path": None,
            "line_number": None,
            "full_trace": stack_trace[:500]
        }
        
        # Try to extract exception type
        exception_pattern = r"([A-Za-z]+Exception|Error):"
        exception_match = re.search(exception_pattern, stack_trace)
        if exception_match:
            result["exception_type"] = exception_match.group(1)
        
        # Try multiple file/line patterns
        patterns = [
            # Pattern 1: "at fastapi/applications.py:10" or "at File.java:123"
            r"at\s+([\w./-]+\.\w+):(\d+)",
            # Pattern 2: File "path/to/file.py", line 123
            r'File "([^"]+)", line (\d+)',
            # Pattern 3: (File.java:123)
            r"\(([\w./-]+\.\w+):(\d+)\)",
            # Pattern 4: simple file:line
            r"([\w./-]+\.\w+):(\d+)",
            # Pattern 5: Java style: com.Class.method(File.java:123)
            r"\(([\w./-]+\.\w+):(\d+)\)"
        ]
        
        for pattern in patterns:
            match = re.search(pattern, stack_trace)
            if match:
                result["file_path"] = match.group(1)
                result["line_number"] = int(match.group(2))
                break
        
        # If file_path contains spaces or is None, try to find a valid path
        if not result["file_path"] or " " in str(result["file_path"]):
            # Look for any valid file path pattern
            path_pattern = r'([\w./-]+\.\w+):(\d+)'
            match = re.search(path_pattern, stack_trace)
            if match:
                result["file_path"] = match.group(1)
                result["line_number"] = int(match.group(2))
        
        return result
    
    def _mock_service(self, service_name: str) -> dict:
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
    
    def _mock_services_list(self) -> list:
        return [
            {"name": "payment-api", "description": "Payment processing", "on_call": ["@rahul", "@priya"], "dependencies": ["auth", "ledger"], "is_critical": True},
            {"name": "auth", "description": "Authentication", "on_call": ["@amit"], "dependencies": [], "is_critical": True},
            {"name": "ledger", "description": "Transaction ledger", "on_call": ["@sneha"], "dependencies": ["database"], "is_critical": True},
            {"name": "refund", "description": "Refund processing", "on_call": ["@ananya"], "dependencies": ["payment-api"], "is_critical": False},
            {"name": "fraud", "description": "Fraud detection", "on_call": ["@raj"], "dependencies": ["payment-api"], "is_critical": False},
            {"name": "notification", "description": "Notifications", "on_call": ["@kavya"], "dependencies": ["user"], "is_critical": False},
            {"name": "user", "description": "User management", "on_call": ["@arjun"], "dependencies": [], "is_critical": False},
            {"name": "database", "description": "Database ops", "on_call": ["@shreya"], "dependencies": [], "is_critical": True},
        ]
        
    