# Contributing to AEGIS PRO

Thanks for helping. AEGIS PRO is an AI incident commander: alert (or a public repo URL) in, a reviewed fix PR out. Keep changes small, testable, and honest about what is real GitHub data versus model output.

## License

This repo is [Business Source License 1.1](LICENSE.md). Contributions are accepted under that license. Do not copy substantial code from projects with incompatible licenses.

## Setup

```bash
git clone https://github.com/MakerYuichi/Aegis-pro.git
cd Aegis-pro
cp backend/orchestrator/.env.example backend/orchestrator/.env
cp frontend/.env.example frontend/.env

docker-compose --env-file demo.env up -d
cd frontend && npm install && npm run dev
```

Backend tests do not need Compose. They mock GitHub, Redis, and the LLM.

```bash
cd backend/orchestrator
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
LLM_PROVIDER=mock LLM_FALLBACKS= pytest tests/ -v
```

Frontend:

```bash
cd frontend
npm run lint
npm run build
```

## Branch and PR conventions

Branch from `main` with a prefix that matches existing work:

- `feat/` — user-visible behavior
- `fix/` — bugs
- `chore/` — deps, CI, seed data
- `test/` — coverage only

Commit messages follow the same shape: `feat(demo): …`, `fix(ci): …`, `test(llm): …`.

Open a PR against `main`. CI (`.github/workflows/llm-provider-ci.yml`) runs the full backend suite with `LLM_PROVIDER=mock` and Redis. CodeQL runs on `main` and PRs.

## Where to change things

| Area | Path |
|---|---|
| Public demo pipeline | `backend/orchestrator/src/demo/` |
| Demo HTTP | `backend/orchestrator/src/demo/endpoints.py` |
| LLM providers | `backend/orchestrator/src/llm/` |
| Incidents, RAG, GitHub, Slack | `backend/orchestrator/src/services/` |
| Dashboard + `/demo` UI | `frontend/src/` |
| Shared incident render | `frontend/src/components/IncidentView.tsx` |
| Schema / seed | `database/` |

The demo file selector (`file_selector.py`) is a **pure function**. Do not add I/O there. GitHub fetches belong in `github_fetcher.py` and must stay mocked in tests.

## Rules that keep the product honest

- Do not fabricate GitHub URLs, SHAs, PR numbers, or related-change scores.
- LLM helpers must not raise on bad model output. Return `None` / a clear error the API can surface.
- `AUTO_FIX_MODE` defaults to `read_only`. Do not add a write path that bypasses it.
- No live network in `pytest`. If you add a GitHub or LLM client, mock it.
- Do not commit `.env`, tokens, or dumps (`backup.sql` is gitignored for a reason).

## Tests to add

If you touch a module under `src/demo/`, extend the matching `tests/test_*.py`. High-value cases:

- Malformed LLM JSON (truncated, missing keys, invalid severity)
- File selector traps (docs/tutorials vs library code)
- Repo parser error reasons (no silent success)
- Auto-fix mode routing

## Pull request checklist

- [ ] Tests added or updated; `pytest` green locally with `LLM_PROVIDER=mock`
- [ ] No secrets in the diff
- [ ] README / architecture updated if you changed the pipeline or an env flag
- [ ] Frontend: exercised `/demo` or the affected dashboard route if you changed UI

## Security

Report vulnerabilities privately to makeryuichii@gmail.com. Do not open a public issue for exploitable bugs.

## Questions

Open a GitHub issue for product or design discussion. For commercial licensing, use the same email as above.
