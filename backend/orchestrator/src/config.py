from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql://postgres:postgres@postgres:5432/aegis"
    
    # Redis
    REDIS_URL: str = "redis://redis:6379/0"
    
    # LLM - Groq
    GROQ_API_KEY: Optional[str] = None
    
    # LLM - OpenRouter
    OPENROUTER_API_KEY: Optional[str] = None
    OPENROUTER_MODEL: Optional[str] = None
    
    # LLM - Google Gemini
    GOOGLE_API_KEY: Optional[str] = None
    
    # GitHub
    GITHUB_TOKEN: Optional[str] = None
    GITHUB_ORG: str = "your-org"
    
    # Slack
    SLACK_BOT_TOKEN: Optional[str] = None
    SLACK_SIGNING_SECRET: Optional[str] = None
    SLACK_APP_TOKEN: Optional[str] = None
    SLACK_WEBHOOK_URL: Optional[str] = None
    
    # Kubernetes (optional)
    K8S_API_URL: Optional[str] = None
    K8S_TOKEN: Optional[str] = None
    K8S_NAMESPACE: str = "production"
    
    # App
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    DEBUG: bool = True
    APP_ENV: str = "development"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

settings = Settings()
