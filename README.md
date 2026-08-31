# 🚀 AEGIS PRO

**AI Incident Commander that turns chaotic war rooms into 10-second actionable briefings**

## Problem

When an incident strikes at 2 AM:
- 50 engineers join a war room
- 20 minutes wasted figuring out WHO owns the service
- 10 more minutes finding WHAT changed
- 30+ minutes to resolution

## Solution

AEGIS PRO analyzes the incident and provides:
- **Who** is on-call
- **What** changed (recent PRs)
- **Why** it broke (stack trace + git blame)
- **How** to fix it (rollback command + similar incidents)

## Tech Stack

- **Frontend:** React + TypeScript + D3.js + Tailwind
- **Backend:** FastAPI (Python) + Spring Boot (Java) + gRPC
- **Database:** PostgreSQL + pgvector + Redis
- **AI:** Groq (Mixtral) + Sentence Transformers (RAG)
- **Infra:** Docker + Docker Compose

## Quick Start

```bash
# Clone the repo
git clone https://github.com/your-username/aegis-pro.git
cd aegis-pro

# Copy environment variables
cp backend/orchestrator/.env.example .env

# Start services
docker-compose up -d

# Seed services
curl -X POST http://localhost:8000/api/v1/services/seed

# Declare an incident
curl -X POST http://localhost:8000/api/v1/incident/declare \
  -H "Content-Type: application/json" \
  -d '{"service_name": "payment-api", "message": "Payment failures detected"}'