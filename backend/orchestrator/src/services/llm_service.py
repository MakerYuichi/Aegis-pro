from groq import Groq
from src.config import settings
from loguru import logger
import json
import re

class LLMService:
    def __init__(self):
        if settings.GROQ_API_KEY:
            self.client = Groq(api_key=settings.GROQ_API_KEY)
            self.model = "mixtral-8x7b-32768"
            logger.info("✅ Groq LLM initialized")
        else:
            logger.warning("⚠️ No GROQ_API_KEY found. Using mock responses.")
            self.client = None
    
    async def analyze_incident(
        self,
        service_name: str,
        message: str,
        stack_analysis: dict,
        blast_radius: dict
    ) -> dict:
        """Analyze incident using Groq LLM"""
        
        if not self.client:
            return self._mock_response(service_name, message)
        
        try:
            prompt = self._build_prompt(
                service_name=service_name,
                message=message,
                stack_analysis=stack_analysis,
                blast_radius=blast_radius
            )
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": """You are an expert SRE analyzing a production incident.
                        Respond with ONLY valid JSON containing:
                        {
                            "severity": "P0" or "P1" or "P2",
                            "title": "short title",
                            "root_cause": "2-3 sentence explanation",
                            "suggested_fix": "1-2 sentence fix",
                            "rollback_command": "kubectl rollout undo deploy/SERVICE -n production",
                            "confidence": 0.0 to 1.0
                        }"""
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=500
            )
            
            content = response.choices[0].message.content
            
            # Extract JSON
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                return result
            
            return self._mock_response(service_name, message)
            
        except Exception as e:
            logger.error(f"LLM error: {e}")
            return self._mock_response(service_name, message)
    
    def _build_prompt(self, **kwargs) -> str:
        prompt = f"""
        Service: {kwargs['service_name']}
        Message: {kwargs['message']}
        """
        
        if kwargs.get('stack_analysis'):
            sa = kwargs['stack_analysis']
            prompt += f"""
        Stack Trace:
        - Exception: {sa.get('exception_type', 'Unknown')}
        - File: {sa.get('file_path', 'Unknown')}
        - Line: {sa.get('line_number', 'Unknown')}
        """
        
        if kwargs.get('blast_radius'):
            br = kwargs['blast_radius']
            prompt += f"""
        Blast Radius:
        - Affected Services: {br.get('affected', [])}
        - Count: {br.get('count', 0)}
        - Severity: {br.get('severity', 'UNKNOWN')}
        """
        
        return prompt
    
    def _mock_response(self, service_name: str, message: str) -> dict:
        """Mock response when no API key"""
        return {
            "severity": "P1",
            "title": f"{service_name} incident detected",
            "root_cause": "Recent change caused service degradation. Check recent deployments.",
            "suggested_fix": f"Rollback the latest deployment of {service_name}",
            "rollback_command": f"kubectl rollout undo deploy/{service_name} -n production",
            "confidence": 0.65
        }