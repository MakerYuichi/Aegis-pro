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
    
    # Verifier — sandboxed test execution before reporting a fix.
    # Off by default until the hosted Docker implementation is proven
    # in production. When false, the pipeline runs as if verification
    # succeeded, with reason="disabled" recorded so downstream
    # consumers can tell the difference.
    VERIFY_BEFORE_REPORT: bool = False
    VERIFY_TIMEOUT_SECONDS: int = 120
    VERIFY_MAX_ATTEMPTS: int = 2
    VERIFY_DOCKER_IMAGE_PYTHON: str = "python:3.11-slim"
    VERIFY_DOCKER_IMAGE_NODE: str = "node:20-slim"
    
    # Verifier work directory.
    # The verifier clones the target repo into VERIFIER_HOST_WORKDIR/<uuid>
    # on the host, then asks the Docker daemon to bind-mount that path
    # into the sandbox container. Because the daemon interprets paths
    # against the HOST filesystem — not against the orchestrator's own
    # filesystem — this value must be the host-side absolute path of the
    # bind mount declared in docker-compose.yml.
    #
    # In docker-compose.yml the mount is:
    #     ./verifier-workdir:/verifier-workdir
    # so the host-side path is the absolute path of ./verifier-workdir
    # on the machine running docker-compose.
    #
    # Default is a Linux path that works in the standard compose layout.
    # Override in .env for Docker Desktop (Mac/Windows) or a custom layout.
    VERIFIER_HOST_WORKDIR: str = "/var/lib/aegis/verifier-workdir"
    VERIFIER_CONTAINER_WORKDIR: str = "/verifier-workdir"
    VERIFIER_MEMORY_LIMIT: str = "1g"
    VERIFIER_CPU_LIMIT: str = "1"
    
    CURATOR_FEW_SHOT: bool = False
    CURATOR_MAX_OUTCOMES: int = 3
    
    INVESTIGATOR_MODE: str = "stage"
    INVESTIGATOR_MAX_ITERATIONS: int = 5
    INVESTIGATOR_TIME_BUDGET_SECONDS: float = 30.0
    
    INVESTIGATOR_MODE: str = "stage"
    INVESTIGATOR_MAX_ITERATIONS: int = 5
    INVESTIGATOR_TIME_BUDGET_SECONDS: float = 30.0
    # Clone-once support for the Investigator agent. When the agent
    # needs filesystem access, it clones the target repo here and
    # writes the path into context["repo_workdir"]. Later stages
    # (Verifier) reuse the same checkout instead of cloning again.
    #
    # INVESTIGATOR_CLONE_TIMEOUT_SECONDS bounds the git clone. A
    # large monorepo can exceed this — the clone fails, the agent's
    # tools all return repo_not_found, and the agent refuses. That's
    # an honest degradation, not a silent failure.
    INVESTIGATOR_CLONE_TIMEOUT_SECONDS: int = 60
    # Base directory for the clone. Empty means "use a tempdir under
    # the system temp root". Set explicitly when you want clones to
    # land somewhere inspectable, e.g. /var/lib/aegis/investigator-workdir.
    
    INVESTIGATOR_WORKDIR: str = ""
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
