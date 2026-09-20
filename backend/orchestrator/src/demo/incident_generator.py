from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any
import hashlib

from src.demo.repo_parser import ParseResult


# ── Scenario templates per language ─────────────────────────────────────
#
# Each entry produces a (title, description, exception_type, file_template,
# line_number, root_cause, suggested_fix) tuple. The file path template
# uses {package} which is derived from the repo name.

_JAVA_SCENARIOS = [
    {
        "title": "UPI Payment Failure — Null Pointer in Reference Resolution",
        "description": "Elevated payment failures since the last deploy. All failing requests share the same stack signature.",
        "exception_type": "NullPointerException",
        "file_template": "src/main/java/com/{package}/{Service}.java",
        "line": 442,
        "root_cause": "A recent refactor removed a null guard on the gateway response. The gateway intermittently returns a response without a reference id on failure.",
        "suggested_fix": "Restore the null guard before accessing the response. Fall back to a request-scoped identifier when the gateway omits the reference.",
    },
    {
        "title": "Elevated Latency — Connection Pool Contention",
        "description": "Service p99 latency 3x baseline since ~40 minutes ago. Correlates with pool saturation.",
        "exception_type": "TimeoutException",
        "file_template": "src/main/java/com/{package}/{Service}.java",
        "line": 214,
        "root_cause": "Long-running queries are holding connections open past their expected duration. Pool size has not been adjusted since traffic grew.",
        "suggested_fix": "Kill idle connections older than 60s, increase pool size, and move heavy reads to a replica.",
    },
]

_PYTHON_SCENARIOS = [
    {
        "title": "AttributeError in request handler",
        "description": "Requests intermittently returning 500. All failing requests share the same trace.",
        "exception_type": "AttributeError",
        "file_template": "src/{package}/handlers.py",
        "line": 142,
        "root_cause": "A recent change removed a null-check on an optional field returned by the upstream client. The client omits the field on certain error paths.",
        "suggested_fix": "Use getattr with a default, or check the field explicitly before access.",
    },
    {
        "title": "Database connection pool exhausted",
        "description": "All request paths hitting connection timeouts. Pool is at max connections.",
        "exception_type": "TimeoutError",
        "file_template": "src/{package}/db/pool.py",
        "line": 88,
        "root_cause": "Long-running background jobs are holding transactions open past their expected duration.",
        "suggested_fix": "Bound the transaction lifetime, increase pool size, and move the background job to a read replica.",
    },
]

_GO_SCENARIOS = [
    {
        "title": "Context deadline exceeded during scoring",
        "description": "Scoring calls hitting the request budget under peak load. Requests failing by default on timeout.",
        "exception_type": "context.DeadlineExceeded",
        "file_template": "internal/{package}/score.go",
        "line": 142,
        "root_cause": "Model inference p99 has grown as the feature set expanded. The request budget was set before the last model revision.",
        "suggested_fix": "Raise the budget in the short term. Retrain with the feature set pruned to the top signals.",
    },
]

_NODE_SCENARIOS = [
    {
        "title": "TypeError: Cannot read properties of undefined",
        "description": "Requests intermittently failing. All failures share the same handler.",
        "exception_type": "TypeError",
        "file_template": "src/{package}/handlers/checkout.ts",
        "line": 118,
        "root_cause": "An optional field on the request payload is not being validated before use. The field is absent on a subset of traffic.",
        "suggested_fix": "Add an explicit validation step before accessing the field. Return 400 on missing data instead of 500.",
    },
]

_RUST_SCENARIOS = [
    {
        "title": "called `Option::unwrap()` on a `None` value",
        "description": "Worker panic under specific input conditions. Process exits, supervisor restarts.",
        "exception_type": "panic",
        "file_template": "src/{package}/handler.rs",
        "line": 87,
        "root_cause": "An unwrap on an optional value that is legitimately None on certain inputs.",
        "suggested_fix": "Replace unwrap with explicit match and return a typed error. Log the input that triggered it.",
    },
]

_SCENARIOS_BY_LANGUAGE = {
    "Java": _JAVA_SCENARIOS,
    "Python": _PYTHON_SCENARIOS,
    "Go": _GO_SCENARIOS,
    "Node": _NODE_SCENARIOS,
    "Rust": _RUST_SCENARIOS,
}

_EXT_BY_LANGUAGE = {
    "Java": "java",
    "Python": "py",
    "Go": "go",
    "Node": "ts",
    "Rust": "rs",
}


# ── Helpers ─────────────────────────────────────────────────────────────

def _package_from_repo(org: str, repo: str) -> str:
    """Turn 'charge-service' into 'chargeservice' (Java) or 'charge_service' (Python)."""
    return "".join(ch for ch in repo if ch.isalnum())


def _package_for_language(org: str, repo: str, language: str) -> str:
    base = _package_from_repo(org, repo)
    if language == "Python":
        # python prefers snake_case
        return _snake(repo)
    return base


def _snake(s: str) -> str:
    out = []
    for ch in s:
        if ch.isupper():
            out.append("_" + ch.lower())
        elif ch in "-.":
            out.append("_")
        else:
            out.append(ch)
    result = "".join(out).strip("_")
    return result or "app"


def _service_name_from_repo(repo: str) -> str:
    # 'charge-service' -> 'ChargeService'
    parts = [p for p in repo.replace("_", "-").split("-") if p]
    if not parts:
        return "Service"
    return "".join(p.capitalize() for p in parts)


def _stable_hash(*parts: str) -> int:
    joined = "|".join(parts)
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()
    return int(digest[:12], 16)


def _pick_scenario(language: str, seed: int) -> dict:
    scenarios = _SCENARIOS_BY_LANGUAGE.get(language) or _JAVA_SCENARIOS
    return scenarios[seed % len(scenarios)]


def _make_stack_trace(
    language: str,
    package: str,
    service: str,
    file_path: str,
    line: int,
    exception_type: str,
) -> str:
    if language == "Java":
        fqcn = f"com.{package}.{service}"
        return (
            f"{exception_type}: Cannot invoke method on null value\n"
            f"\tat {fqcn}.process({file_path.split('/')[-1]}:{line})\n"
            f"\tat {fqcn}.handle({file_path.split('/')[-1]}:{line - 12})"
        )
    if language == "Python":
        return (
            f"Traceback (most recent call last):\n"
            f'  File "{file_path}", line {line}, in handle_request\n'
            f"    result = payload.get_value()\n"
            f"{exception_type}: 'NoneType' object has no attribute 'get_value'"
        )
    if language == "Go":
        return (
            f"panic: {exception_type}\n\n"
            f"goroutine 1 [running]:\n"
            f"{package}/internal/handler.process(0x0, 0x0)\n"
            f"\t{file_path}:{line} +0x1a2\n"
            f"{package}/internal/handler.Handle(...)\n"
            f"\t{file_path}:{line - 20}"
        )
    if language == "Node":
        return (
            f"{exception_type}: Cannot read properties of undefined (reading 'value')\n"
            f"    at handleRequest ({file_path}:{line}:18)\n"
            f"    at processTicksAndRejections (node:internal/process/task_queues:95:5)"
        )
    if language == "Rust":
        return (
            f"thread 'main' panicked at '{file_path}:{line}':\n"
            f"called `Option::unwrap()` on a `None` value\n"
            f"note: run with `RUST_BACKTRACE=1` for a backtrace"
        )
    return f"{exception_type}\n\tat {file_path}:{line}"


def _make_blame(org: str, repo: str, service: str, seed: int) -> dict:
    handle = f"eng-lead@{org}.com"
    pr_number = 100 + (seed % 200)
    sha = hashlib.sha1(f"{org}/{repo}/{seed}".encode()).hexdigest()[:8]
    return {
        "commit_hash": sha,
        "author": handle,
        "author_avatar": None,
        "message": f"refactor({service.lower()}): tighten error handling",
        "line": seed % 500 + 50,
        "file": None,  # filled by caller
        "pr_number": pr_number,
        "pr_title": f"refactor: simplify {service} error handling",
        "pr_url": f"https://github.com/{org}/{repo}/pull/{pr_number}",
        "pr_author": handle,
        "contributors": [
            {"username": handle, "role": "author", "avatar": None, "url": None},
        ],
    }


def _make_related_prs(org: str, repo: str, service: str, seed: int) -> list[dict]:
    pr1 = 100 + (seed % 200)
    pr2 = 100 + ((seed // 7) % 200)
    handle = f"eng-lead@{org}.com"
    return [
        {
            "number": pr1,
            "title": f"refactor({service.lower()}): tighten error handling",
            "author": handle,
            "url": f"https://github.com/{org}/{repo}/pull/{pr1}",
            "merged_at": "2026-09-14T18:32:00Z",
            "files": ["(see blame)"],
            "relevance_score": 0.93,
            "reason": f"PR #{pr1} directly modified the failing file at the incident line and removed a guard.",
        },
        {
            "number": pr2,
            "title": f"chore({service.lower()}): bump dependencies",
            "author": f"dependabot[bot]@{org}",
            "url": f"https://github.com/{org}/{repo}/pull/{pr2}",
            "merged_at": "2026-09-12T11:04:00Z",
            "files": ["pom.xml" if "Java" else "package.json"],
            "relevance_score": 0.31,
            "reason": "Dependency bump — same repository, unlikely related to the failure.",
        },
    ]


def _make_code_context(file_path: str, line: int) -> dict:
    snippet_lines = []
    start = max(1, line - 5)
    for i in range(start, line + 4):
        marker = ">>> " if i == line else "    "
        snippet_lines.append(f"{i:4d} {marker}// line {i}")
    return {
        "file_path": file_path,
        "line_number": line,
        "total_lines": 612,
        "code_snippet": "\n".join(snippet_lines),
        "full_file": None,
        "simulated": True,
    }


def _make_auto_fix(seed: int) -> dict:
    return {
        "status": "pr_draft",
        "approved": False,
        "requires_approval": True,
        "mode": "pr_draft",
        "approval_url": "/approve/INC-DEMO",
        "fix_preview": "@@ -1,3 +1,3 @@ - guarded response access + added null check",
        "explanation": "Add a null guard before accessing the response field. Fall back to a request-scoped identifier.",
        "pr": {
            "status": "pr_draft",
            "approval_required": True,
            "approval_url": "/approve/INC-DEMO",
        },
    }


# ── Public entry point ──────────────────────────────────────────────────

def generate_incident(parsed: ParseResult, seed: int) -> dict[str, Any]:
    """
    Build a synthetic incident matching the frontend `Incident` type.

    Deterministic: same (parsed.org, parsed.repo, seed) → same output.
    """
    if not parsed.ok:
        raise ValueError("generate_incident called with a failed ParseResult")

    org = parsed.org or "org"
    repo = parsed.repo or "repo"
    language = parsed.language_hint or "Java"

    scenario = _pick_scenario(language, seed)
    service = _service_name_from_repo(repo)
    package = _package_for_language(org, repo, language)

    file_path = scenario["file_template"].format(
        package=package, Service=service
    )
    line = scenario["line"]

    incident_id = "INC-DEMO-" + hashlib.sha1(
        f"{org}/{repo}/{seed}".encode()
    ).hexdigest()[:8].upper()

    # Deterministic declared_at, within the last 6 hours.
    base = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
    declared_at = base + timedelta(minutes=(seed % 360))
    declared_at_iso = declared_at.isoformat().replace("+00:00", "Z")

    confidence = 0.72 + ((seed % 24) / 100.0)  # 0.72 .. 0.95

    stack_trace = _make_stack_trace(
        language, package, service, file_path, line, scenario["exception_type"]
    )

    blame = _make_blame(org, repo, service, seed)
    blame["file"] = file_path
    related_prs = _make_related_prs(org, repo, service, seed)
    code_context = _make_code_context(file_path, line)
    auto_fix = _make_auto_fix(seed)

    affected = [repo, "auth", "ledger"]
    if language != "Java":
        affected = [repo, "auth"]

    return {
        "incident_id": incident_id,
        "service_name": repo,
        "severity": "P0" if (seed % 4 == 0) else "P1",
        "status": "active",
        "title": scenario["title"],
        "description": scenario["description"],
        "stack_trace": stack_trace,
        "exception_type": scenario["exception_type"],
        "file_path": file_path,
        "line_number": line,
        "root_cause": scenario["root_cause"],
        "suggested_fix": scenario["suggested_fix"],
        "rollback_command": f"kubectl rollout undo deploy/{repo} -n production",
        "confidence_score": round(confidence, 2),
        "declared_at": declared_at_iso,
        "affected_services": affected,
        "extra_metadata": {
            "simulated": True,
            "demo_default": False,
            "rag_context_used": False,
            "github": {
                "blame": blame,
                "related_prs": related_prs,
            },
            "code_context": code_context,
            "auto_fix": auto_fix,
        },
    }
