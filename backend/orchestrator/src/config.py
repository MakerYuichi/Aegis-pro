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
    VERIFY_DOCKER_IMAGE_PYTHON: str = "aegis-verifier:latest"
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
    VERIFIER_CONTAINER_WORKDIR: str = "/work"
    VERIFIER_MEMORY_LIMIT: str = "1g"
    VERIFIER_CPU_LIMIT: str = "1"
    
    # --- Prefetch (Phase 3, verifier dependency install) ----------
    #
    # The prefetcher runs in a throwaway container with network but
    # no secrets. It reads the repo's manifest, sanitizes it, and
    # downloads wheels into a persistent cache. The verifier
    # (unchanged here) will mount the cache read-only and install
    # from it with --no-index --require-hashes.
    #
    # VERIFIER_PIP_CACHE_HOST_DIR is a HOST path. It must resolve
    # on the machine running docker-compose, because the daemon
    # bind-mounts it into the verification container. In the
    # compose layout, the same host directory is also mounted into
    # the orchestrator at the same path — so reads and writes from
    # the orchestrator see the cache directly.
    VERIFIER_PIP_CACHE_HOST_DIR: str = "/var/lib/aegis/pip-cache"
    VERIFIER_PIP_CACHE_CONTAINER_DIR: str = "/verifier-pip-cache"

    # Name of the user-defined Docker network the prefetcher runs
    # on. The network's resolver only answers for hosts in
    # src.agents.prefetch.policy.ALLOWED_HOSTS. See
    # docker-compose.yml for the network definition.
    VERIFIER_PREFETCH_NETWORK: str = "aegis-prefetch"

    # Bound on the prefetcher container's wall-clock time. First
    # run for a repo can be slow (torch wheels); warm runs are
    # fast. 600s is generous.
    VERIFIER_PREFETCH_TIMEOUT_SECONDS: int = 1800

    # Same shape as the verifier container's limits. The prefetcher
    # downloads; it doesn't run tests, so the memory need is lower.
    VERIFIER_PREFETCH_MEMORY_LIMIT: str = "512m"
    VERIFIER_PREFETCH_CPU_LIMIT: str = "1"
    
        # --- Build (sdist-only packages, PR C1b) ----------------------
    #
    # The build container turns an sdist into a wheel. It runs with
    # --network none, --read-only, --cap-drop ALL. See
    # src/agents/mirror/build.py for the full flag list.

    BUILD_CONTAINER_IMAGE: str = "aegis-builder:latest"
    BUILD_CONTAINER_TIMEOUT_SECONDS: int = 600
    BUILD_CONTAINER_MEMORY_LIMIT: str = "1g"
    BUILD_CONTAINER_CPU_LIMIT: str = "2"

    # Hard cap on a built wheel's size before the orchestrator will
    # accept it. The largest legitimate wheels are ~50MB; a
    # 200MB wheel is an indication of a bad build, not a real one.
    BUILD_WHEEL_MAX_BYTES: int = 200 * 1024 * 1024

    # The mirror directory on the host. Symmetric mount: the
    # orchestrator sees it at /mirror (container path); the daemon
    # sees it at the value below (host path). The two namespaces
    # must never be confused — see src/agents/prefetch/runner.py.
    MIRROR_HOST_DIR: str = "/var/lib/aegis/mirror"
    MIRROR_CONTAINER_DIR: str = "/mirror"
    
    # --- Build resolver (sdist-only packages, PR C1a) ------------
    #
    # The resolver reads an sdist's [build-system].requires and
    # resolves each entry to an exact version, bounded by the
    # sdist's own upload date. Pure Python; no Docker. Adds a
    # minimal set of tunables rather than a policy surface.

    # HTTP timeout for the PyPI JSON API. PyPI's JSON is cached at
    # their edge; a slow response is a signal, not a nuisance.
    BUILD_RESOLVER_TIMEOUT_SECONDS: int = 15

    # User agent sent to PyPI. Their docs ask for a descriptive one.
    BUILD_RESOLVER_USER_AGENT: str = "aegis-pro-build-resolver/0.1"

    # Hard cap on the sdist tarball's size before the reader will
    # even try to open it. Protects against absurd inputs.
    BUILD_RESOLVER_MAX_SDIST_BYTES: int = 200 * 1024 * 1024  # 200 MB

    # Hard cap on the number of build requirements an sdist may
    # declare. Real sdists have 1-5; a hundred is a signal.
    BUILD_RESOLVER_MAX_REQUIREMENTS: int = 50
    BUILD_RESOLVER_MAX_DECOMPRESSED_BYTES: int = 500 * 1024 * 1024
    BUILD_SMOKE_TIMEOUT_SECONDS: int = 60
    BUILD_ON_MISS_ENABLED: bool = True
    
    CURATOR_FEW_SHOT: bool = False
    CURATOR_MAX_OUTCOMES: int = 3
    
    INVESTIGATOR_MODE: str = "stage"
    INVESTIGATOR_MAX_ITERATIONS: int = 8
    INVESTIGATOR_TIME_BUDGET_SECONDS: float = 300.0
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
    
    INVESTIGATOR_WORKDIR: str = "/work-investigator"
    
    # ------------------------------------------------------------------
    # Scanner — v1.0 Phase 1/2
    # ------------------------------------------------------------------
    # manual | scheduled
    #
    # "manual" is the only implemented mode. Scans run only when
    # invoked via `aegis scan <repo>` or POST /api/v1/scan.
    #
    # "scheduled" is a placeholder for v1.0 Phase 6 (Scheduling &
    # Delivery). Selecting it raises NotImplementedError at the
    # point of the mistake — same discipline as
    # get_verifier(has_runner=True) raising instead of returning a
    # stub. A silent scheduled mode would look like a working
    # setting that quietly does nothing.
    SCANNER_MODE: str = "manual"

    # Top-N files to scan. Overridable per-call.
    SCANNER_TOP_N: int = 25

    # Churn window (days) for the file_selector. Overridable per-call.
    SCANNER_SINCE_DAYS: int = 30

    # Hard cap on candidates scored in one scan. Protects against a
    # pathological repo where every file fires every pattern.
    SCANNER_MAX_CANDIDATES: int = 100
    SCANNER_MAX_INCIDENTS: int = 10
    
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
