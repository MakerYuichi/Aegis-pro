import asyncio
from src.services.incident_service import IncidentService
from src.services.github_service import GitHubService
from src.database import get_db
from src.models import Incident
from sqlalchemy import select
from loguru import logger

async def reprocess_all():
    gh_service = GitHubService()
    
    session = await get_db()
    
    try:
        # Get ALL incidents
        result = await session.execute(
            select(Incident).order_by(Incident.declared_at.desc())
        )
        incidents = result.scalars().all()
        
        logger.info(f'📋 Found {len(incidents)} total incidents')
        
        updated_count = 0
        skipped_count = 0
        
        for incident in incidents:
            try:
                stack_trace = incident.stack_trace
                
                # Skip if no stack trace
                if not stack_trace:
                    skipped_count += 1
                    continue
                
                # Parse file and line from stack trace
                file_path = None
                line_number = None
                repo_name = None
                
                if 'at ' in stack_trace:
                    parts = stack_trace.split('at ')[-1].split(':')
                    if len(parts) >= 2:
                        file_path = parts[0].strip()
                        try:
                            line_number = int(parts[1].strip())
                        except:
                            line_number = 1
                
                if not file_path:
                    skipped_count += 1
                    continue
                
                # Determine repo based on file path
                if 'rnp.cpp' in file_path or 'stream-parse.cpp' in file_path or 'rnp' in file_path:
                    repo_name = 'rnpgp/rnp'
                elif 'fastapi' in file_path:
                    repo_name = 'fastapi/fastapi'
                else:
                    # Try to find repo from service
                    service_name = incident.service_name
                    if service_name == 'payment-api':
                        repo_name = 'fastapi/fastapi'
                    else:
                        # Skip if we can't determine repo
                        skipped_count += 1
                        continue
                
                logger.info(f'🔄 Processing {incident.incident_id} - {file_path}:{line_number} ({repo_name})')
                
                # Get related PRs with LLM scoring
                related_prs = await gh_service.get_related_prs(
                    repo_name, file_path, line_number
                )
                
                # Update incident
                extra_metadata = incident.extra_metadata or {}
                if 'github' not in extra_metadata:
                    extra_metadata['github'] = {}
                
                extra_metadata['github']['related_prs'] = related_prs
                extra_metadata['github']['file_path'] = file_path
                extra_metadata['github']['line_number'] = line_number
                extra_metadata['github']['repo'] = repo_name
                
                incident.extra_metadata = extra_metadata
                await session.commit()
                
                updated_count += 1
                logger.info(f'✅ Updated {incident.incident_id} with {len(related_prs)} PRs')
                
                if related_prs:
                    pr = related_prs[0]
                    logger.info(f'   Top PR #{pr["number"]}: {pr.get("relevance_score")} - {pr.get("reason")[:80]}...')
                
            except Exception as e:
                logger.error(f'❌ Failed {incident.incident_id}: {e}')
                await session.rollback()
                continue
        
        logger.info(f'✅ Done! Updated {updated_count} incidents, skipped {skipped_count}')
        
    except Exception as e:
        logger.error(f'❌ Database error: {e}')
        await session.rollback()
    finally:
        await session.close()

if __name__ == "__main__":
    asyncio.run(reprocess_all())
