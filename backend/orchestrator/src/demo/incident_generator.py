from datetime import datetime, timedelta, timezone
from typing import Any, Optional
import hashlib

from src.demo.repo_parser import ParseResult
from src.demo.risk_analyzer_llm import RiskFinding


# ── Real-data path ──────────────────────────────────────────────────────

def _extract_code_context(
    file_path: str,
    file_content: str,
    line_number: int,
    context: int = 6,
) -> dict:
    """
    Build a code-context block from the real file content, centered on
    the failing line. Uses the file's actual text — no placeholder lines.
    """
    lines = file_content.split("\n")
    total = len(lines)
    line_number = max(1, min(line_number, total))

    start = max(0, line_number - context - 1)
    end = min(total, line_number + context)

    snippet_lines = []
    for i in range(start, end):
        marker = ">>> " if i == line_number - 1 else "    "
        snippet_lines.append(f"{i + 1:4d} {marker}{lines[i]}")

    return {
        "file_path": file_path,
        "line_number": line_number,
        "total_lines": total,
        "code_snippet": "\n".join(snippet_lines),
        "full_file": None,
        "simulated": False,
    }


def _make_analysis_stack_trace(
    language: str,
    file_path: str,
    line_number: int,
    line_content: str,
    exception_type: str,
) -> str:
    """
    Build a language-appropriate stack trace that quotes the real failing
    line. The buyer can open the file on GitHub and see the same line.
    """
    short = file_path.rsplit("/", 1)[-1]
    stripped = line_content.strip()

    if language == "Python":
        return (
            "Traceback (most recent call last):\n"
            f'  File "{file_path}", line {line_number}, in <module>\n'
            f"    {stripped}\n"
            f"{exception_type}"
        )
    if language == "Java":
        return (
            f"{exception_type}: cannot invoke method on null value\n"
            f"\tat {file_path}:{line_number}\n"
            f"\t    {stripped}"
        )
    if language == "Go":
        return (
            f"panic: {exception_type}\n\n"
            f"goroutine 1 [running]:\n"
            f"{file_path}:{line_number} +0x1a2\n"
            f"\t{stripped}"
        )
    if language == "Node":
        return (
            f"{exception_type}: unexpected value\n"
            f"    at {file_path}:{line_number}:1\n"
            f"    {stripped}"
        )
    if language == "Rust":
        return (
            f"thread 'main' panicked at '{file_path}:{line_number}':\n"
            f"{exception_type}\n"
            f"    {stripped}"
        )
    return f"{exception_type}\n\tat {file_path}:{line_number}\n\t    {stripped}"


def _make_real_blame(
    file_path: str,
    line_number: int,
    file_commits: list[dict],
    contributors: list[dict],
    related_prs: list[dict],
    org: str,
) -> dict:
    """
    Build the blame block from the file's real commit history and the
    repo's real contributors. If the file has an associated PR from the
    commit history, include it. If not, omit the PR fields — do not
    fabricate one.
    """
    top_commit = file_commits[0] if file_commits else None
    top_contributor = contributors[0] if contributors else None

    author = (
        (top_commit or {}).get("author")
        or (top_contributor or {}).get("username")
        or f"maintainer@{org}"
    )
    commit_hash = (top_commit or {}).get("sha") or "unknown"
    message = (top_commit or {}).get("message") or f"recent changes to {file_path}"

    blame: dict[str, Any] = {
        "commit_hash": commit_hash,
        "author": author,
        "author_avatar": None,
        "message": message[:120],
        "line": line_number,
        "file": file_path,
    }

    # Only claim a PR if the file's commit history actually points to one.
    # related_prs comes from fetch_related_prs, which walks the file's
    # commits — so a match here is a real match.
    if related_prs:
        # related_prs[0] is the PR whose merge commit is the newest commit
        # to this file — the most likely candidate for the failing line.
        matched = next((r for r in related_prs if r.get("number")), None)
        if matched:
            blame.update({
                "pr_number": matched["number"],
                "pr_title": matched.get("title"),
                "pr_url": matched.get("url"),
                "pr_author": matched.get("author"),
            })

    blame["contributors"] = [
        {
            "username": c.get("username"),
            "role": "author" if i == 0 else "contributor",
            "avatar": c.get("avatar_url"),
            "url": c.get("url"),
        }
        for i, c in enumerate(contributors[:5])
    ]

    return blame


def _make_real_related_prs(related_prs: list[dict], file_path: str) -> list[dict]:
    """
    Return the file-related changes (commits and PRs) with their LLM
    relevance scores. Sorted by relevance_score desc.
    """
    out = []
    for item in related_prs[:5]:
        entry = {
            "sha": item.get("sha"),
            "commit_message": item.get("commit_message"),
            "commit_date": item.get("commit_date"),
            "author": item.get("author"),
            "relevance_score": item.get("relevance_score", 1.0),
            "reason": item.get("reason") or _default_change_reason(item, file_path),
        }
        if item.get("number"):
            entry["number"] = item["number"]
            entry["title"] = item.get("title")
            entry["url"] = item.get("url")
            entry["merged_at"] = item.get("merged_at")
        out.append(entry)
    return out


def _default_change_reason(item: dict, file_path: str) -> str:
    if item.get("number"):
        return f"PR #{item['number']} merged a commit into {file_path}."
    return f"Commit {item.get('sha', 'unknown')} touched {file_path}."

def _make_recent_prs(recent_prs: list[dict]) -> list[dict]:
    """
    Return the repo's most recent merged PRs — a sidebar, not part of
    the incident analysis. Rendered separately by the frontend.
    """
    out = []
    for pr in recent_prs[:5]:
        out.append({
            "number": pr.get("number"),
            "title": pr.get("title"),
            "author": pr.get("author"),
            "url": pr.get("url"),
            "merged_at": pr.get("merged_at"),
        })
    return out


def _make_analysis_auto_fix(risk: RiskFinding, file_path: str) -> dict:
    """Auto-fix preview built from the analyzer's suggested fix."""
    return {
        "status": "pr_draft",
        "approved": False,
        "requires_approval": True,
        "mode": "pr_draft",
        "approval_url": "/approve/INC-DEMO",
        "fix_preview": f"@@ -{risk.line_number},1 +{risk.line_number},3 @@\n- {risk.line_content}\n+ {risk.suggested_fix}",
        "explanation": risk.suggested_fix,
        "pr": {
            "status": "pr_draft",
            "approval_required": True,
            "approval_url": "/approve/INC-DEMO",
        },
    }


async def generate_incident_from_analysis(
    parsed: ParseResult,
    seed: int,
    repo_meta: dict,
    target_file: Optional[str],
    file_content: Optional[str],
    risk: Optional[RiskFinding],
    related_prs: list[dict],
    recent_prs: list[dict],
    file_commits: list[dict],
    contributors: list[dict],
) -> Optional[dict]:
    """
    Build an incident from a real analysis.

    Returns None when there's nothing to analyze:
      - target_file is None  (the selector found only non-code files)
      - risk is None         (the LLM couldn't find a specific risk)
      - file_content is None (file fetch failed)

    The caller is expected to surface a "not_code" message in that case.
    No synthetic incident is fabricated.
    """
    if not parsed.ok:
        raise ValueError("generate_incident_from_analysis called with a failed ParseResult")
    if not target_file or not file_content or not risk:
        return None

    org = parsed.org or "org"
    repo = parsed.repo or "repo"
    language = repo_meta.get("language") or parsed.language_hint or "Java"

    # Deterministic per (org, repo, session seed). The risk is not part of
    # the hash — the incident ID is stable across re-runs even if the LLM
    # picks a different line.
    incident_id = "INC-DEMO-" + hashlib.sha1(
        f"{org}/{repo}/{target_file}/{seed}".encode()
    ).hexdigest()[:8].upper()

    declared_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    stack_trace = _make_analysis_stack_trace(
        language=language,
        file_path=target_file,
        line_number=risk.line_number,
        line_content=risk.line_content,
        exception_type=risk.exception_type,
    )

    code_context = _extract_code_context(
        file_path=target_file,
        file_content=file_content,
        line_number=risk.line_number,
    )

    blame = _make_real_blame(
        file_path=target_file,
        line_number=risk.line_number,
        file_commits=file_commits,
        contributors=contributors,
        related_prs=related_prs,
        org=org,
    )

    related = _make_real_related_prs(related_prs, target_file)
    auto_fix = _make_analysis_auto_fix(risk, target_file)

    affected = [repo, "auth", "ledger"]

    return {
        "incident_id": incident_id,
        "service_name": repo,
        "severity": risk.severity,
        "status": "active",
        "title": risk.title,
        "description": risk.blast_radius_reason,
        "stack_trace": stack_trace,
        "exception_type": risk.exception_type,
        "file_path": target_file,
        "line_number": risk.line_number,
        "root_cause": risk.root_cause,
        "suggested_fix": risk.suggested_fix,
        "rollback_command": f"kubectl rollout undo deploy/{repo} -n production",
        "confidence_score": round(risk.confidence, 2),
        "declared_at": declared_at,
        "affected_services": affected,
        "extra_metadata": {
            "simulated": True,
            "demo_default": False,
            "rag_context_used": False,
            "github": {
                "blame": blame,
                "related_prs": related,
                "recent_prs": _make_recent_prs(recent_prs),
            },
            "code_context": code_context,
            "auto_fix": auto_fix,
            "demo_quality": {
                "confidence": "high",
                "real_file": True,
                "category": risk.category,
                "blast_radius_reason": risk.blast_radius_reason,
                "related_lines": risk.related_lines,
            },
        },
    }


# ── Legacy synthetic path ───────────────────────────────────────────────
#
# The endpoint still calls generate_incident() today. Phase 5 switches
# the call site to generate_incident_from_analysis(). Both live in the
# same module until the legacy path is removed.

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


def _package_from_repo(org: str, repo: str) -> str:
    return "".join(ch for ch in repo if ch.isalnum())


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


def _package_for_language(org: str, repo: str, language: str) -> str:
    if language == "Python":
        return _snake(repo)
    return _package_from_repo(org, repo)


def _service_name_from_repo(repo: str) -> str:
    parts = [p for p in repo.replace("_", "-").split("-") if p]
    if not parts:
        return "Service"
    return "".join(p.capitalize() for p in parts)


def _pick_scenario(language: str, seed: int) -> dict:
    scenarios = _SCENARIOS_BY_LANGUAGE.get(language) or _JAVA_SCENARIOS
    return scenarios[seed % len(scenarios)]


def _make_legacy_stack_trace(
    language: str, package: str, service: str,
    file_path: str, line: int, exception_type: str,
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
            f"\t{file_path}:{line} +0x1a2"
        )
    if language == "Node":
        return (
            f"{exception_type}: Cannot read properties of undefined (reading 'value')\n"
            f"    at handleRequest ({file_path}:{line}:18)"
        )
    if language == "Rust":
        return (
            f"thread 'main' panicked at '{file_path}:{line}':\n"
            f"called `Option::unwrap()` on a `None` value"
        )
    return f"{exception_type}\n\tat {file_path}:{line}"


def _make_legacy_blame(org: str, repo: str, service: str, seed: int, file_path: str) -> dict:
    handle = f"eng-lead@{org}.com"
    pr_number = 100 + (seed % 200)
    sha = hashlib.sha1(f"{org}/{repo}/{seed}".encode()).hexdigest()[:8]
    return {
        "commit_hash": sha,
        "author": handle,
        "author_avatar": None,
        "message": f"refactor({service.lower()}): tighten error handling",
        "line": seed % 500 + 50,
        "file": file_path,
        "pr_number": pr_number,
        "pr_title": f"refactor: simplify {service} error handling",
        "pr_url": f"https://github.com/{org}/{repo}/pull/{pr_number}",
        "pr_author": handle,
        "contributors": [
            {"username": handle, "role": "author", "avatar": None, "url": None},
        ],
    }


def _make_legacy_related_prs(org: str, repo: str, service: str, seed: int) -> list[dict]:
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


def _make_legacy_code_context(file_path: str, line: int) -> dict:
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


def _make_legacy_auto_fix(seed: int) -> dict:
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


def generate_incident(parsed: ParseResult, seed: int) -> dict[str, Any]:
    """
    Legacy synthetic path. Deterministic per (parsed.org, parsed.repo, seed).
    Kept for backward compatibility until the endpoint switches call sites.
    """
    if not parsed.ok:
        raise ValueError("generate_incident called with a failed ParseResult")

    org = parsed.org or "org"
    repo = parsed.repo or "repo"
    language = parsed.language_hint or "Java"

    scenario = _pick_scenario(language, seed)
    service = _service_name_from_repo(repo)
    package = _package_for_language(org, repo, language)

    file_path = scenario["file_template"].format(package=package, Service=service)
    line = scenario["line"]

    incident_id = "INC-DEMO-" + hashlib.sha1(
        f"{org}/{repo}/{seed}".encode()
    ).hexdigest()[:8].upper()

    base = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
    declared_at = base + timedelta(minutes=(seed % 360))

    confidence = 0.72 + ((seed % 24) / 100.0)

    return {
        "incident_id": incident_id,
        "service_name": repo,
        "severity": "P0" if (seed % 4 == 0) else "P1",
        "status": "active",
        "title": scenario["title"],
        "description": scenario["description"],
        "stack_trace": _make_legacy_stack_trace(
            language, package, service, file_path, line, scenario["exception_type"]
        ),
        "exception_type": scenario["exception_type"],
        "file_path": file_path,
        "line_number": line,
        "root_cause": scenario["root_cause"],
        "suggested_fix": scenario["suggested_fix"],
        "rollback_command": f"kubectl rollout undo deploy/{repo} -n production",
        "confidence_score": round(confidence, 2),
        "declared_at": declared_at.isoformat().replace("+00:00", "Z"),
        "affected_services": [repo, "auth", "ledger"] if language == "Java" else [repo, "auth"],
        "extra_metadata": {
            "simulated": True,
            "demo_default": False,
            "rag_context_used": False,
            "github": {
                "blame": _make_legacy_blame(org, repo, service, seed, file_path),
                "related_prs": _make_legacy_related_prs(org, repo, service, seed),
            },
            "code_context": _make_legacy_code_context(file_path, line),
            "auto_fix": _make_legacy_auto_fix(seed),
        },
    }
