from groq import Groq
from src.config import settings
from loguru import logger
import json
import re

class LLMService:
    def __init__(self):
        self.client = None
        if settings.GROQ_API_KEY and settings.GROQ_API_KEY != "":
            try:
                self.client = Groq(api_key=settings.GROQ_API_KEY)
                # Working models from the API response
                self.models = [
                    "openai/gpt-oss-20b",        # Fast, good quality
                    "groq/compound",              # Groq's own model
                    "qwen/qwen3.6-27b",           # Alibaba's model
                ]
                logger.info(f"✅ Groq LLM initialized with {len(self.models)} models")
            except Exception as e:
                logger.warning(f"⚠️ Groq initialization failed: {e}")
                self.client = None
        else:
            logger.warning("⚠️ No GROQ_API_KEY found. Using intelligent mock.")
    
    async def analyze_incident(
        self,
        service_name: str,
        message: str,
        stack_analysis: dict,
        blast_radius: dict
    ) -> dict:
        """Analyze incident using Groq LLM or intelligent mock"""
        
        # Try Groq first if available
        if self.client:
            result = await self._try_llm_analysis(
                service_name, message, stack_analysis, blast_radius
            )
            if result:
                return result
        
        # Fallback to intelligent mock
        return self._intelligent_mock(service_name, message, stack_analysis, blast_radius)
    
    async def _try_llm_analysis(self, service_name, message, stack_analysis, blast_radius):
        """Try LLM analysis with fallback models"""
        prompt = self._build_prompt(service_name, message, stack_analysis, blast_radius)
        
        for model in self.models:
            try:
                logger.info(f"🔄 Trying model: {model}")
                response = self.client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "system",
                            "content": """You are an expert SRE. Respond with ONLY valid JSON:
{
    "severity": "P0" or "P1" or "P2",
    "title": "Short title",
    "root_cause": "2-3 sentence explanation",
    "suggested_fix": "1-2 sentence fix",
    "rollback_command": "kubectl command",
    "confidence": 0.0-1.0
}"""
                        },
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.1,
                    max_tokens=300
                )
                
                content = response.choices[0].message.content
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group())
                    logger.info(f"✅ LLM succeeded with {model}")
                    return result
                    
            except Exception as e:
                logger.warning(f"❌ Model {model} failed: {e}")
                continue
        
        return None
    
    def _build_prompt(self, service_name, message, stack_analysis, blast_radius):
        prompt = f"Service: {service_name}\nMessage: {message}\n"
        
        if stack_analysis:
            prompt += f"Stack: {stack_analysis.get('exception_type', 'Unknown')} at {stack_analysis.get('file_path', 'unknown')}:{stack_analysis.get('line_number', 'unknown')}\n"
        
        if blast_radius:
            prompt += f"Affected Services: {', '.join(blast_radius.get('affected', []))}\nCount: {blast_radius.get('count', 0)}\n"
        
        return prompt
    
    def _intelligent_mock(self, service_name, message, stack_analysis, blast_radius):
        """Intelligent mock response that actually helps"""
        severity = "P1"
        title = f"{service_name} incident"
        root_cause = "Recent change caused service degradation"
        suggested_fix = f"Rollback {service_name} deployment"
        confidence = 0.65
        
        # Parse NullPointerException
        if "NullPointerException" in message or "null" in message.lower():
            severity = "P0"
            title = f"Critical NullPointerException in {service_name}"
            root_cause = "Null check missing in code. Check the file and line from the stack trace."
            suggested_fix = "Add null checks and proper error handling. If urgent, rollback the latest change."
            confidence = 0.85
        
        # Parse Timeout
        elif "Timeout" in message or "timeout" in message.lower():
            severity = "P1"
            title = f"Timeout issues in {service_name}"
            root_cause = "External service or database is responding slowly"
            suggested_fix = "Increase timeout values or optimize queries. Check downstream dependencies."
            confidence = 0.75
        
        # Parse SQL errors
        elif "SQLException" in message or "sql" in message.lower():
            severity = "P1"
            title = f"Database error in {service_name}"
            root_cause = "SQL query failed or database connection issue"
            suggested_fix = "Check database connection pool and recent schema changes"
            confidence = 0.78
        
        # High blast radius
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
