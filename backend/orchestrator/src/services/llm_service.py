from src.config import settings
from loguru import logger
import json
import re

from src.llm.base import LLMProviderError
from src.llm.factory import get_provider_chain


class LLMService:
    def __init__(self):
        self.chain = None
        try:
            self.chain = get_provider_chain()
            logger.info(f"✅ LLMService chain: {self.chain.provider_names()}")
        except LLMProviderError as e:
            logger.warning(f"⚠️ No LLM providers configured: {e}")

    async def analyze_incident(
        self,
        service_name: str,
        message: str,
        stack_analysis: dict,
        blast_radius: dict,
        rag_context: str = ""
    ) -> dict:
        """Analyze incident using the configured provider chain."""
        prompt = self._build_prompt(
            service_name, message, stack_analysis, blast_radius, rag_context
        )
        system = (
            "You are an expert SRE. Use the provided context (similar past incidents) "
            "to respond with ONLY valid JSON:\n"
            "{\n"
            '    "severity": "P0" or "P1" or "P2",\n'
            '    "title": "Short title",\n'
            '    "root_cause": "2-3 sentence explanation",\n'
            '    "suggested_fix": "1-2 sentence fix",\n'
            '    "rollback_command": "kubectl command",\n'
            '    "confidence": 0.0-1.0\n'
            "}"
        )

        if self.chain:
            resp = await self.chain.complete(prompt=prompt, system=system)
            if resp:
                parsed = self._extract_json(resp.content)
                if parsed:
                    logger.info(
                        f"✅ Incident analyzed via {resp.provider}/{resp.model}"
                    )
                    return parsed
                logger.warning(
                    f"⚠️ Provider {resp.provider} returned unparseable content; "
                    f"falling back to intelligent mock"
                )

        logger.warning("⚠️ All LLM providers failed. Using intelligent mock.")
        return self._intelligent_mock(service_name, message, stack_analysis, blast_radius)

    @staticmethod
    def _extract_json(content: str) -> dict | None:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            return None
    
    def _build_prompt(self, service_name, message, stack_analysis, blast_radius, rag_context):
        """Build prompt for LLM with RAG context"""
        prompt = f"Service: {service_name}\nMessage: {message}\n"
        
        if stack_analysis:
            prompt += f"Stack: {stack_analysis.get('exception_type', 'Unknown')} at {stack_analysis.get('file_path', 'unknown')}:{stack_analysis.get('line_number', 'unknown')}\n"
        
        if blast_radius:
            prompt += f"Affected Services: {', '.join(blast_radius.get('affected', []))}\nCount: {blast_radius.get('count', 0)}\n"
        
        if rag_context:
            prompt += f"\n{rag_context}\n"
        
        prompt += '\nRespond with JSON: {"severity": "P0|P1|P2", "title": "...", "root_cause": "...", "suggested_fix": "...", "rollback_command": "...", "confidence": 0.0-1.0}'
        
        return prompt
    
    def _intelligent_mock(self, service_name, message, stack_analysis, blast_radius):
        """Intelligent mock response that actually helps"""
        severity = "P1"
        title = f"{service_name} incident"
        root_cause = "Recent change caused service degradation"
        suggested_fix = f"Rollback {service_name} deployment"
        confidence = 0.65
        
        if "NullPointerException" in message:
            severity = "P0"
            title = f"Critical NullPointerException in {service_name}"
            root_cause = "Null check missing in code. Check the file and line from the stack trace."
            suggested_fix = "Add null checks and proper error handling. If urgent, rollback the latest change."
            confidence = 0.85
        elif "Timeout" in message:
            severity = "P1"
            title = f"Timeout issues in {service_name}"
            root_cause = "External service or database is responding slowly"
            suggested_fix = "Increase timeout values or optimize queries"
            confidence = 0.75
        
        if blast_radius and blast_radius.get("count", 0) > 3:
            severity = "P0" if severity == "P1" else severity
            root_cause += f" - Affects {blast_radius.get('count', 0)} services"
        
        return {
            "severity": severity,
            "title": title,
            "root_cause": root_cause,
            "suggested_fix": suggested_fix,
            "rollback_command": f"kubectl rollout undo deploy/{service_name} -n production",
            "confidence": confidence
        }
        
    async def complete_raw(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1000,
    ) -> str | None:
        """Call the chain with a raw prompt. Returns the raw text, or None."""
        if not self.chain:
            return None
        resp = await self.chain.complete(
            prompt=prompt,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return resp.content if resp else None
