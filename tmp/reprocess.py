docker exec -i aegis-orchestrator python -c "
import asyncio
from src.database import get_db
from src.models import Incident
from sqlalchemy import select
from loguru import logger

async def check_incidents():
    session = await get_db()
    try:
        result = await session.execute(
            select(Incident).where(
                Incident.stack_trace.like('%fastapi/applications.py%')
            ).order_by(Incident.declared_at.desc())
        )
        incidents = result.scalars().all()
        
        llm_scored = []
        heuristic = []
        no_prs = []
        error_prs = []
        
        for inc in incidents:
            extra = inc.extra_metadata or {}
            github = extra.get('github', {})
            related_prs = github.get('related_prs', [])
            
            if not related_prs:
                no_prs.append({
                    'id': inc.incident_id,
                    'title': inc.title[:50],
                    'stack': inc.stack_trace[:50] if inc.stack_trace else 'No stack'
                })
            elif related_prs and related_prs[0].get('relevance_score') == 0.7:
                heuristic.append({
                    'id': inc.incident_id,
                    'title': inc.title[:50],
                    'top_pr': related_prs[0].get('number', 'N/A'),
                    'reason': related_prs[0].get('reason', '')[:50]
                })
            else:
                llm_scored.append({
                    'id': inc.incident_id,
                    'title': inc.title[:50],
                    'score': related_prs[0].get('relevance_score', 0),
                    'top_pr': related_prs[0].get('number', 'N/A'),
                    'reason': related_prs[0].get('reason', '')[:60]
                })
        
        # Print summary
        logger.info('=' * 60)
        logger.info(f'📊 Total Incidents: {len(incidents)}')
        logger.info('=' * 60)
        logger.info(f'✅ LLM Scored (0.85-0.95): {len(llm_scored)}')
        logger.info(f'⚠️  Heuristic Only (0.7): {len(heuristic)}')
        logger.info(f'❌ No PRs Found: {len(no_prs)}')
        logger.info('=' * 60)
        
        # Show LLM scored incidents
        if llm_scored:
            logger.info('\n✅ LLM SCORED INCIDENTS:')
            for inc in llm_scored[:10]:
                logger.info(f'  • {inc["id"]} -> Score: {inc["score"]} | PR #{inc["top_pr"]} | {inc["reason"][:40]}...')
            if len(llm_scored) > 10:
                logger.info(f'  ... and {len(llm_scored) - 10} more')
        
        # Show heuristic incidents (need fixing)
        if heuristic:
            logger.info('\n⚠️  HEURISTIC ONLY (NEED FIXING):')
            for inc in heuristic:
                logger.info(f'  • {inc["id"]} -> PR #{inc["top_pr"]} | {inc["reason"][:40]}...')
            logger.info(f'\n  Total: {len(heuristic)} incidents need reprocessing')
        
        # Show no PRs
        if no_prs:
            logger.info('\n❌ NO PRS FOUND:')
            for inc in no_prs:
                logger.info(f'  • {inc["id"]} | {inc["stack"]}...')
            logger.info(f'\n  Total: {len(no_prs)} incidents have no related PRs')
            
        logger.info('\n' + '=' * 60)
        logger.info('💡 ACTION ITEMS:')
        if heuristic:
            logger.info(f'  • Reprocess {len(heuristic)} incidents to get LLM scores')
        if no_prs:
            logger.info(f'  • Check why {len(no_prs)} incidents have no PRs')
        logger.info('=' * 60)
        
    finally:
        await session.close()

asyncio.run(check_incidents())
