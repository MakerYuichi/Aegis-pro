from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    # Auth0
    AUTH0_DOMAIN: str = ""
    AUTH0_AUDIENCE: str = ""
  
    # Database
    DATABASE_URL: str = "postgresql://postgres:postgres@postgres:5432/aegis"

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"

    # LLM - Groq
    GROQ_API_KEY: Optional[str] = None
    GROQ_MODEL: Optional[str] = None  

    # LLM - OpenRouter
    OPENROUTER_API_KEY: Optional[str] = None
    OPENROUTER_MODEL: Optional[str] = None
    
    # LLM provider selection
    LLM_PROVIDER: str = "groq"           # groq | azure | ollama | gemini | openrouter | mock
    LLM_FALLBACKS: str = "gemini,openrouter" 

    # LLM - Google Gemini
    GOOGLE_API_KEY: Optional[str] = None
    
    # Azure OpenAI
    AZURE_OPENAI_API_KEY: Optional[str] = None
    AZURE_OPENAI_ENDPOINT: Optional[str] = None
    AZURE_OPENAI_DEPLOYMENT: Optional[str] = None
    AZURE_OPENAI_API_VERSION: str = "2024-10-21"
    
    # Ollama
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.1"

    # GitHub
    GITHUB_TOKEN: Optional[str] = None
    GITHUB_ORG: str = "your-org"

    # Slack
    SLACK_BOT_TOKEN: Optional[str] = None
    SLACK_SIGNING_SECRET: Optional[str] = None
    SLACK_APP_TOKEN: Optional[str] = None
    SLACK_WEBHOOK_URL: Optional[str] = None
    
    # Auto-fix safety
    AUTO_FIX_MODE: str = "read_only"
    
    # Demo mode — enables public demo endpoints and mock services
    DEMO_MODE: bool = False

    # Kubernetes (optional)
    K8S_API_URL: Optional[str] = None
    K8S_TOKEN: Optional[str] = None
    K8S_NAMESPACE: str = "production"
    
    ADMIN_EMAILS: str = ""

    # App
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    DEBUG: bool = True
    APP_ENV: str = "development"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

settings = Settings()
