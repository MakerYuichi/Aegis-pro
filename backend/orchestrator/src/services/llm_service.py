from groq import Groq
from src.config import settings
from loguru import logger
import json
import re

class LLMService:
    def __init__(self):
        if settings.GROQ_API_KEY and settings.GROQ_API_KEY != "":
            try:
                self.client = Groq(api_key=settings.GROQ_API_KEY)
                # Updated to the latest model
                self.model = "llama-3.1-70b-versatile"  # Or "llama-3.1-8b-instant" for faster responses
                logger.info(f"✅ Groq LLM initialized with model: {self.model}")
            except Exception as e:
                logger.error(f"❌ Failed to initialize Groq: {e}")
                self.client = None
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
            logger.info("Using mock response (no LLM client)")
            return self._mock_response(service_name, message)
        
        try:
            prompt = self._build_prompt(
                service_name=service_name,
                message=message,
                stack_analysis=stack_analysis,
                blast_radius=blast_radius
            )
            
            logger.info(f"Sending to LLM: {prompt[:200]}...")
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": """You are an expert SRE. Analyze this incident and respond with ONLY valid JSON. No other text.

Example response:
{
    "severity": "P0",
    "title": "Critical NullPointerException in payment-api",
    "root_cause": "Null check missing in PaymentProcessor.java:442 caused UPI flow to fail",
    "suggested_fix": "Add null check for upiResponse in processUPI method",
    "rollback_command": "kubectl rollout undo deploy/payment-api -n production",
    "confidence": 0.85
}"""
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=300
            )
            
            content = response.choices[0].message.content
            logger.info(f"LLM response: {content[:200]}...")
            
            # Extract JSON
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                try:
                    result = json.loads(json_match.group())
                    logger.info(f"✅ LLM analysis successful: {result}")
                    return result
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse JSON: {e}")
            else:
                logger.error("No JSON found in LLM response")
            
            return self._mock_response(service_name, message)
            
        except Exception as e:
            logger.error(f"LLM error: {e}")
            return self._mock_response(service_name, message)
    
    def _build_prompt(self, **kwargs) -> str:
        """Build prompt for LLM"""
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
- Affected Services: {', '.join(br.get('affected', []))}
- Count: {br.get('count', 0)}
- Severity: {br.get('severity', 'UNKNOWN')}
"""
        
        prompt += """
Provide JSON analysis with: severity (P0/P1/P2), title, root_cause, suggested_fix, rollback_command, confidence (0-1)
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
