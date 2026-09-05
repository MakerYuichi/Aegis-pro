from groq import Groq
from src.config import settings
from loguru import logger
import json
import re
import httpx

# Try to import Google Gemini
try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    logger.warning("⚠️ Google Gemini SDK not installed. Install: pip install google-generativeai")

class LLMService:
    def __init__(self):
        self.client = None
        self.openrouter_api_key = None
        self.gemini_client = None
        
        # Initialize Groq
        if settings.GROQ_API_KEY and settings.GROQ_API_KEY != "":
            try:
                self.client = Groq(api_key=settings.GROQ_API_KEY)
                self.models = [
                    "openai/gpt-oss-20b",
                    "groq/compound",
                    "qwen/qwen3.6-27b",
                ]
                logger.info(f"✅ Groq LLM initialized with {len(self.models)} models")
            except Exception as e:
                logger.warning(f"⚠️ Groq initialization failed: {e}")
                self.client = None
        else:
            logger.warning("⚠️ No GROQ_API_KEY found.")
        
        # Initialize Google Gemini
        if getattr(settings, 'GOOGLE_API_KEY', None):
            try:
                if GEMINI_AVAILABLE:
                    genai.configure(api_key=settings.GOOGLE_API_KEY)
                    self.gemini_client = genai.GenerativeModel('models/gemini-3.5-flash-lite')
                    logger.info("✅ Google Gemini initialized (model: models/gemini-3.5-flash-lite)")
                else:
                    logger.warning("⚠️ Google Gemini SDK not installed")
            except Exception as e:
                logger.warning(f"⚠️ Gemini initialization failed: {e}")
                self.gemini_client = None
        else:
            logger.warning("⚠️ No GOOGLE_API_KEY found.")
        
        # Initialize OpenRouter
        self.openrouter_api_key = getattr(settings, 'OPENROUTER_API_KEY', None)
        self.openrouter_model = getattr(settings, 'OPENROUTER_MODEL', "google/gemma-4-31b-it:free")
        self.openrouter_fallback_models = [
            "google/gemma-4-26b-a4b-it:free",
            "nvidia/nemotron-3-ultra-550b-a55b:free",
            "cohere/north-mini-code:free",
            "z-ai/glm-5.2:free"
        ]
        if self.openrouter_api_key:
            logger.info(f"✅ OpenRouter initialized (primary model: {self.openrouter_model})")
            logger.info(f"   Fallback models: {len(self.openrouter_fallback_models)} available")
        else:
            logger.warning("⚠️ No OPENROUTER_API_KEY found")
    
    async def analyze_incident(
        self,
        service_name: str,
        message: str,
        stack_analysis: dict,
        blast_radius: dict,
        rag_context: str = ""
    ) -> dict:
        """Analyze incident using Groq first, then Gemini, then OpenRouter as fallback"""
        
        # Try Groq first
        if self.client:
            result = await self._try_llm_analysis(
                service_name, message, stack_analysis, blast_radius, rag_context, provider="groq"
            )
            if result:
                return result
        
        # Try Gemini as second fallback
        if self.gemini_client:
            logger.info("🔄 Groq failed or unavailable, trying Google Gemini...")
            result = await self._try_llm_analysis(
                service_name, message, stack_analysis, blast_radius, rag_context, provider="gemini"
            )
            if result:
                return result
        
        # Try OpenRouter as third fallback
        if self.openrouter_api_key:
            logger.info("🔄 Gemini failed, trying OpenRouter...")
            result = await self._try_llm_analysis(
                service_name, message, stack_analysis, blast_radius, rag_context, provider="openrouter"
            )
            if result:
                return result
        
        # Final fallback to intelligent mock
        logger.warning("⚠️ All LLM providers failed. Using intelligent mock.")
        return self._intelligent_mock(service_name, message, stack_analysis, blast_radius)
    
    async def _try_llm_analysis(self, service_name, message, stack_analysis, blast_radius, rag_context, provider="groq"):
        """Try LLM analysis with Groq, Gemini, or OpenRouter"""
        prompt = self._build_prompt(service_name, message, stack_analysis, blast_radius, rag_context)
        
        if provider == "groq":
            return await self._call_groq(prompt)
        elif provider == "gemini":
            return await self._call_gemini(prompt)
        elif provider == "openrouter":
            return await self._call_openrouter_with_fallback(prompt)
        
        return None
    
    async def _call_groq(self, prompt):
        """Call Groq API"""
        for model in self.models:
            try:
                logger.info(f"🔄 Trying Groq model: {model}")
                response = self.client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "system",
                            "content": """You are an expert SRE. Use the provided context (similar past incidents) to respond with ONLY valid JSON:
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
                    logger.info(f"✅ Groq succeeded with {model}")
                    return result
                    
            except Exception as e:
                logger.warning(f"❌ Groq model {model} failed: {e}")
                continue
        
        return None
    
    async def _call_gemini(self, prompt):
        """Call Google Gemini API"""
        try:
            logger.info(f"🔄 Trying Google Gemini...")
            
            # Gemini uses a different API format
            response = self.gemini_client.generate_content(prompt)
            content = response.text
            
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                logger.info("✅ Google Gemini succeeded")
                return result
            else:
                logger.warning(f"❌ Gemini returned no JSON: {content[:100]}")
                
        except Exception as e:
            logger.warning(f"❌ Google Gemini failed: {e}")
        
        return None
    
    async def _call_openrouter_with_fallback(self, prompt):
        """Call OpenRouter API with fallback models"""
        models_to_try = [self.openrouter_model] + self.openrouter_fallback_models
        
        for model in models_to_try:
            try:
                logger.info(f"🔄 Trying OpenRouter model: {model}")
                result = await self._call_openrouter(prompt, model)
                if result:
                    logger.info(f"✅ OpenRouter succeeded with {model}")
                    return result
            except Exception as e:
                logger.warning(f"❌ OpenRouter model {model} failed: {e}")
                continue
        
        return None
    
    async def _call_openrouter(self, prompt, model=None):
        """Call OpenRouter API with specific model"""
        try:
            if model is None:
                model = self.openrouter_model
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.openrouter_api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "http://localhost:8000",
                        "X-Title": "AEGIS PRO"
                    },
                    json={
                        "model": model,
                        "messages": [
                            {
                                "role": "system",
                                "content": """You are an expert SRE. Use the provided context (similar past incidents) to respond with ONLY valid JSON:
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
                        "temperature": 0.1,
                        "max_tokens": 300
                    }
                )
                
                if response.status_code == 200:
                    data = response.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    json_match = re.search(r'\{.*\}', content, re.DOTALL)
                    if json_match:
                        return json.loads(json_match.group())
                else:
                    logger.warning(f"OpenRouter failed: {response.status_code}")
                    
        except Exception as e:
            logger.warning(f"OpenRouter error: {e}")
        
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
