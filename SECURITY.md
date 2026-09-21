# Security

## Reporting

Email **makeryuichii@gmail.com** with a description, impact, and reproduction notes. Do not file public GitHub issues for exploitable bugs.

## Defaults that matter

- `AUTO_FIX_MODE=read_only` — the orchestrator will not call GitHub write APIs until you opt in.
- Mutating HTTP routes require an Auth0 JWT.
- Public `/api/v1/demo/*` exists only when `DEMO_MODE=true`. The demo GitHub client is unauthenticated and read-only.
- LLM traffic can stay on your side (`LLM_PROVIDER=ollama` or Azure).

## Secrets

Never commit `.env` files or tokens. Use `backend/orchestrator/.env.example` and `frontend/.env.example`.
