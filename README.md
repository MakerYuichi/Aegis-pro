# AEGIS PRO — AI Incident Commander
 
> **Detects payment failures, finds who broke it, generates the fix, creates the PR. In under 10 seconds.**
 
Built for the [Razorpay AI Buildathon](https://razorpay.com) · Track 02: AI Risk Manager
 
---
 
## The Problem
 
It's 2 AM. A UPI payment failure alert fires. 50 engineers join a war room. 20 minutes pass just figuring out:
- **What** broke?
- **Who** changed it?
- **What** do we do?
By the time someone finds the root cause, customers are affected and revenue is gone.
 
**AEGIS PRO eliminates this chaos entirely.**
 
---
 
## The "Aha" Moment
 
```
Alert fires         → Prometheus/DataDog sends webhook
Auto-detects        → Incident created without manual input
Fetches code        → Actual source from GitHub retrieved
Shows failing line  → Exact line highlighted with context
Shows who broke it  → Git blame: author + commit + PR
Generates fix       → AI-powered diff with explanation
Creates PR          → One-click approval → PR merged
```
 
**Total time: under 10 seconds. No war room needed.**
 
---
 
## Demo
 
> 📹 [Watch 5-minute demo](#) · 🚀 [Live deployment](#) · 📖 [API docs](http://localhost:8000/docs)
 
### Declare via Slack
```
/incident payment-api "UPI payments failing"
```
 
**AEGIS PRO responds instantly:**
```
🚨 Incident INC-20260902-2D6C59
 
Service:     payment-api
Severity:    P0
Confidence:  95%
 
🧠 Root Cause:
NullPointerException at PaymentProcessor.java:442
Recent PR #127 by @engineer removed null guard on UPI response
 
🔧 Suggested Fix:
Add null check on upiResponse before String.equals()
 
📋 Rollback: kubectl rollout undo deployment/payment-api
 
💥 Blast Radius: 4 services — ledger, database, auth, payment-api
 
[🔧 Rollback Now] [📋 View Details] [✅ Acknowledge]
```
 
### Simulate a Monitoring Alert
```bash
curl -X POST http://localhost:8000/webhook/alert \
  -H "Content-Type: application/json" \
  -d '{
    "service": "payment-api",
    "alert": "High error rate detected",
    "stack_trace": "java.lang.NullPointerException at PaymentProcessor.java:442"
  }'
```
 
---
 
## Architecture
 
```
┌─────────────────────────────────────────────────────────┐
│                      AEGIS PRO                          │
├──────────────┬──────────────────┬───────────────────────┤
│  Slack /cmd  │   Web Dashboard  │   Webhook (Prometheus) │
└──────┬───────┴────────┬─────────┴──────────┬────────────┘
       │                │                    │
       └────────────────▼────────────────────┘
                        │
          ┌─────────────▼──────────────┐
          │     FastAPI Backend        │
          │  • Incident Service        │
          │  • RAG Service (pgvector)  │
          │  • LLM Service (Groq)      │
          │  • GitHub Service          │
          │  • WebSocket Manager       │
          │  • On-Call Rotation        │
          └─────────────┬──────────────┘
                        │
          ┌─────────────▼──────────────┐
          │         Databases          │
          │  PostgreSQL + pgvector     │
          │  Redis (cache)             │
          └────────────────────────────┘
```
 
**Tech Stack:**
`Python` · `FastAPI` · `PostgreSQL + pgvector` · `Redis` · `React + TypeScript` · `Tailwind CSS` · `D3.js` · `Docker` · `Groq LLM` · `Sentence Transformers` · `WebSocket`
 
---
 
## Features
 
| Feature | Status |
|---|---|
| Slack `/incident` command with rich Block Kit UI | ✅ |
| Auto-discovery from Prometheus / DataDog webhooks | ✅ |
| Stack trace parsing (Java, Python, Go) | ✅ |
| Blast radius calculation across service graph | ✅ |
| RAG pipeline — learns from historical incidents | ✅ |
| Groq LLM root cause analysis + confidence scoring | ✅ |
| GitHub integration — fetches failing code + git blame | ✅ |
| Auto-fix generation — AI diff with human approval flow | ✅ |
| Automatic PR creation post-approval | ✅ |
| Real-time WebSocket dashboard | ✅ |
| On-call rotation management | ✅ |
| Service dependency graph (D3.js) | ✅ |
| Dark mode | ✅ |
| Dockerized — one command setup | ✅ |

---

## 📊 Dashboard Features

The web dashboard provides complete visibility into your incident landscape:

- **Live Activity Feed** — Real-time stream of all user actions: rollbacks, acknowledgments, approvals
- **Service Health Ring** — Visual health status for every service in your catalog
- **Service Dependency Graph** — Interactive D3.js visualization showing blast radius
- **On-Call Rotation** — Current schedule with primary/secondary/tertiary roles
- **Approval Dashboard** — Pending fixes with diff preview and one-click approve/reject
- **Git Blame & Code Context** — Shows who changed the code and the exact failing line
 
---
 
## How the AI Works
 
### 1. RAG Pipeline
Every incident is embedded as a 384-dimensional vector using `all-MiniLM-L6-v2`. When a new incident fires, AEGIS PRO searches historical incidents via cosine similarity and sends the top 3 matches as context to the LLM — so it learns from your team's own incident history, not generic Stack Overflow answers.
 
### 2. LLM Analysis (Groq)
The LLM receives: stack trace + blast radius + RAG context + actual code from GitHub. It returns structured JSON with severity, root cause, suggested fix, and confidence score.
 
### 3. Auto-Fix Generation
When a file path and line number are identified, AEGIS PRO:
- Fetches the actual code from GitHub
- Sends code context to the LLM
- Gets a diff-based fix with explanation
- Presents it for human approval
- Creates the PR on approval

---
## 👥 On-Call & Team Management

AEGIS PRO includes a complete on-call rotation system:

- Define primary, secondary, and tertiary engineers per service
- Configure escalation policies with wait times
- Alert specific engineers or the entire team from the dashboard
- Visual roster display with role badges
- Add/remove team members via UI or API
---
 
## Getting Started
 
### Prerequisites
- Docker and Docker Compose
- Node.js 18+
- Slack workspace with admin access
- GitHub personal access token
- Groq API key (optional — falls back to intelligent mock)
### Quick Start
```bash
# Clone
git clone https://github.com/MakerYuichi/Aegis-pro.git
cd Aegis-pro
 
# Configure
cp backend/orchestrator/.env.example backend/orchestrator/.env
vim backend/orchestrator/.env
 
# Start everything
docker-compose up -d
sleep 10
 
# Seed service catalog
curl -X POST http://localhost:8000/api/v1/services/seed
 
# API: http://localhost:8000
# Dashboard: http://localhost:5173
# API Docs: http://localhost:8000/docs
```
 
### Environment Variables
```env
# Slack
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=...
SLACK_WEBHOOK_URL=https://hooks.slack.com/...
 
# GitHub
GITHUB_TOKEN=ghp_...
GITHUB_ORG=your-org
 
# LLM
GROQ_API_KEY=gsk_...
 
# Database (auto-configured in Docker)
DATABASE_URL=postgresql+asyncpg://aegis:aegis@localhost/aegis
REDIS_URL=redis://localhost:6379
```
 
---
 
## API Reference
 
| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Health check |
| `/api/v1/services` | GET | List all services |
| `/api/v1/services/seed` | POST | Seed service catalog |
| `/api/v1/incident/declare` | POST | Declare incident manually |
| `/api/v1/incident/{id}` | GET | Get incident details |
| `/api/v1/incidents` | GET | List all incidents |
| `/api/v1/incident/rollback` | POST | Trigger rollback |
| `/api/v1/incident/{id}/approve` | POST | Approve auto-fix PR |
| `/webhook/alert` | POST | Receive monitoring alerts |
| `/slack/events` | POST | Slack event handler |
| `/ws/incidents` | WebSocket | Real-time incident stream |
 
---
 
## Impact
 
| Metric | Without AEGIS PRO | With AEGIS PRO |
|---|---|---|
| Time to identify root cause | 15–20 minutes | 10 seconds |
| Engineers needed in war room | 50 | 1 |
| Time to rollback | 10–15 minutes | 2 minutes |
| Total MTTR | 30–45 minutes | < 5 minutes |
 
---
 
## Why This Is Different
 
Existing tools like PagerDuty and Datadog tell you *that* something broke. AEGIS PRO tells you *why*, *who*, and *what to do* — automatically, using your own incident history and your own codebase.
 
The auto-fix generation with human approval is what no existing tool does end-to-end: detect → diagnose → fetch code → generate fix → create PR.
 
---
 
## Built With
 
- [FastAPI](https://fastapi.tiangolo.com/) — async Python API framework
- [pgvector](https://github.com/pgvector/pgvector) — vector similarity search in PostgreSQL
- [Sentence Transformers](https://www.sbert.net/) — `all-MiniLM-L6-v2` for embeddings
- [Groq](https://groq.com/) — LLM inference
- [React](https://react.dev/) + [TypeScript](https://www.typescriptlang.org/) — frontend
- [D3.js](https://d3js.org/) — service dependency visualization
- [Slack Bolt](https://slack.dev/bolt-python/) — Slack integration
---

 ## 🔧 Engineering Challenges & Solutions
 **Slack 3-Second Timeout** → Slack expects a response within 3 seconds. Our LLM analysis takes 5-10 seconds. Fixed by implementing Slack's `response_url` pattern with background tasks. The command acknowledges immediately, processes asynchronously, and updates the message via webhook.

**GitHub 404 Errors** → The GitHub blame API fails for many repositories. Fixed by falling back to commit history via PyGithub when the blame API returns 404.

**pgvector Syntax Errors** → Parameterized queries don't support `::vector` casting. Fixed by converting embeddings to string format before passing to PostgreSQL.

## License
 
MIT — built for the Razorpay AI Buildathon 2026.
 
---
 
*Built by MakerYuichi · [GitHub](https://github.com/MakerYuichi) 
