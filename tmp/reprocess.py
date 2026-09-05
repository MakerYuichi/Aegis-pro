import sys
import os
import asyncio

sys.path.insert(0, "/app")

from src.services.incident_service import IncidentService
from src.services.github_service import GitHubService
from src.database import get_db
from src.models import Incident
from sqlalchemy import select
from loguru import logger

async def reprocess_all_with_gemini():
    session = await get_db()
    gh_service = GitHubService()
    incident_service = IncidentService()
    
    def get_repo_for_file(file_path):
        if not file_path:
            return None
        file_path_lower = file_path.lower()
        
        if "fastapi" in file_path_lower:
            return "fastapi/fastapi"
        if "rnp.cpp" in file_path_lower or "rnp" in file_path_lower:
            return "rnpgp/rnp"
        if ".java" in file_path_lower:
            if "auth" in file_path_lower:
                return "razorpay/auth-service"
            if "dbconnection" in file_path_lower:
                return "razorpay/database-service"
            if "payment" in file_path_lower:
                return "razorpay/payment-api"
            if "ledger" in file_path_lower:
                return "razorpay/ledger-service"
            if "kafka" in file_path_lower:
                return "razorpay/kafka-service"
            if "jedis" in file_path_lower or "redis" in file_path_lower:
                return "razorpay/cache-service"
            if "jwt" in file_path_lower:
                return "razorpay/auth-service"
            return "razorpay/payment-api"
        if "django" in file_path_lower:
            return "django/django"
        if "flask" in file_path_lower:
            return "pallets/flask"
        return None
    
    try:
        result = await session.execute(
            select(Incident).order_by(Incident.declared_at.desc())
        )
        incidents = result.scalars().all()
        
        logger.info(f"Found {len(incidents)} total incidents")
        
        to_reprocess = []
        already_done = 0
        no_stack = 0
        no_repo = 0
        
        for inc in incidents:
            extra = inc.extra_metadata or {}
            github = extra.get("github", {})
            related_prs = github.get("related_prs", [])
            
            if related_prs and related_prs[0].get("relevance_score", 0) > 0.7:
                already_done += 1
                continue
            
            stack_trace = inc.stack_trace
            if not stack_trace:
                no_stack += 1
                continue
            
            import re
            file_path = None
            line_number = 1
            
            patterns = [
                r"at\s+[\w.]+\.(\w+)\(([\w./-]+\.\w+):(\d+)\)",
                r"at\s+([\w./-]+\.\w+):(\d+)",
                r"([\w./-]+\.\w+):(\d+)",
                r"([A-Za-z]+\.java):(\d+)",
                r"([A-Za-z]+Service):(\d+)",
                r"([A-Za-z]+\.py):(\d+)",
            ]
            for pattern in patterns:
                match = re.search(pattern, stack_trace)
                if match:
                    if len(match.groups()) == 3:
                        file_path = match.group(2)
                        line_number = int(match.group(3))
                    elif len(match.groups()) == 2:
                        file_path = match.group(1)
                        line_number = int(match.group(2))
                    break
            
            if not file_path:
                no_stack += 1
                continue
            
            repo_name = get_repo_for_file(file_path)
            if repo_name:
                to_reprocess.append({
                    "id": inc.incident_id,
                    "file": file_path,
                    "line": line_number,
                    "repo": repo_name,
                })
            else:
                no_repo += 1
        
        logger.info("=" * 70)
        logger.info("REPROCESSING SUMMARY:")
        logger.info(f"   Total Incidents: {len(incidents)}")
        logger.info(f"   Already LLM Scored: {already_done}")
        logger.info(f"   Need Reprocessing: {len(to_reprocess)}")
        logger.info(f"   No Stack Trace: {no_stack}")
        logger.info(f"   No Repo Mapping: {no_repo}")
        logger.info("=" * 70)
        
        if not to_reprocess:
            logger.info("All incidents already have LLM scores!")
            return
        
        batch_size = 3
        fixed = 0
        failed = 0
        
        for i in range(0, len(to_reprocess), batch_size):
            batch = to_reprocess[i:i+batch_size]
            logger.info(f"Batch {i//batch_size + 1}/{(len(to_reprocess)+batch_size-1)//batch_size}")
            
            for inc in batch:
                try:
                    logger.info(f'  Processing {inc["id"]}: {inc["file"]} -> {inc["repo"]} (line {inc["line"]})')
                    
                    related_prs = await gh_service.get_related_prs(
                        inc["repo"], inc["file"], inc["line"]
                    )
                    
                    extra_metadata = {
                        "github": {
                            "related_prs": related_prs,
                            "file_path": inc["file"],
                            "line_number": inc["line"],
                            "repo": inc["repo"],
                            "reprocessed": True,
                            "reprocessed_at": "2026-09-05",
                            "scoring_method": "gemini_detailed_v2"
                        }
                    }
                    
                    result = await incident_service.update_incident(
                        inc["id"], 
                        {"extra_metadata": extra_metadata}
                    )
                    
                    if result.get("status") == "updated":
                        fixed += 1
                        if related_prs:
                            pr = related_prs[0]
                            logger.info(f'  Updated {inc["id"]}: {len(related_prs)} PRs (Top: #{pr["number"]} - {pr.get("relevance_score")})')
                            logger.info(f'     Reason: {pr.get("reason", "")[:80]}...')
                        else:
                            logger.info(f'  Updated {inc["id"]}: no PRs')
                    else:
                        logger.error(f'  Failed to update {inc["id"]}')
                        failed += 1
                        
                except Exception as e:
                    logger.error(f'  Error {inc["id"]}: {str(e)[:100]}')
                    failed += 1
                    continue
            
            logger.info(f"Progress: {fixed} fixed, {failed} failed, {len(to_reprocess) - fixed - failed} remaining")
            
            if i + batch_size < len(to_reprocess):
                logger.info("Waiting 3 seconds before next batch...")
                await asyncio.sleep(3)
        
        logger.info("=" * 70)
        logger.info("FINAL SUMMARY:")
        logger.info(f"   Successfully reprocessed: {fixed}")
        logger.info(f"   Failed: {failed}")
        logger.info(f"   Skipped (no repo mapping): {no_repo}")
        logger.info("=" * 70)
        
        if fixed > 0:
            logger.info("Incidents reprocessed with Gemini!")
        else:
            logger.info("No incidents were reprocessed.")
        
    except Exception as e:
        logger.error(f"Error: {e}")
        await session.rollback()
    finally:
        await session.close()

if __name__ == "__main__":
    asyncio.run(reprocess_all_with_gemini())