"""
Mock GitHub service for DEMO_MODE.

Returns deterministic canned data with the same shapes as GitHubService.
Never touches the network. Every response carries `simulated: True` so the
frontend can render a DEMO badge.

Shape parity contract — the real GitHubService returns:

  get_recent_prs        -> list[dict] with keys:
                           number, title, author, url, merged_at,
                           additions, deletions, files

  get_blame_with_pr     -> dict with keys:
                           commit_hash, author, author_avatar, message,
                           line, file
                           (plus pr_number, pr_title, pr_url, pr_author,
                            contributors when a PR is associated)

  get_related_prs       -> list[dict] with keys:
                           number, title, author, url, merged_at, files
                           (plus relevance_score, reason after scoring)

  get_file_content      -> dict with keys:
                           file_path, line_number, total_lines,
                           code_snippet, full_file

This mock returns the same keys. Regression test in tests/test_mock_services.py
asserts the parity.
"""

from loguru import logger


# ── Static demo data ─────────────────────────────────────────────────────

_DEMO_AUTHOR = "arjun.mehta"
_DEMO_AUTHOR_EMAIL = "arjun.mehta@acme-demo.com"
_DEMO_FILE = "src/main/java/com/acme/payment/PaymentProcessor.java"
_DEMO_LINE = 442


_CODE_SNIPPET = """\
 432     public PaymentResult processUpiPayment(UpiRequest request) {
 433         validateRequest(request);
 434
 435         UpiResponse upiResponse = upiGateway.initiate(request);
 436
 437         // Build the ledger entry from the gateway response
 438         LedgerEntry entry = new LedgerEntry();
 439         entry.setAmount(request.getAmount());
 440         entry.setCurrency(request.getCurrency());
 441
 442 >>>     entry.setReference(upiResponse.getReferenceId());
 443
 444         ledgerClient.record(entry);
 445         return PaymentResult.success(entry.getId());
 446     }
"""


_RECENT_PRS = [
    {
        "number": 127,
        "title": "refactor(upi): simplify response handling",
        "author": _DEMO_AUTHOR,
        "url": "https://github.com/acme-demo/payment-service/pull/127",
        "merged_at": "2026-09-14T18:32:00Z",
        "additions": 12,
        "deletions": 18,
        "files": [_DEMO_FILE],
    },
    {
        "number": 126,
        "title": "chore(deps): bump spring-boot to 3.2.4",
        "author": "priya.singh",
        "url": "https://github.com/acme-demo/payment-service/pull/126",
        "merged_at": "2026-09-13T11:04:00Z",
        "additions": 4,
        "deletions": 4,
        "files": ["pom.xml"],
    },
    {
        "number": 125,
        "title": "feat(ledger): add idempotency key to entries",
        "author": "rahul.kumar",
        "url": "https://github.com/acme-demo/payment-service/pull/125",
        "merged_at": "2026-09-12T09:21:00Z",
        "additions": 47,
        "deletions": 3,
        "files": ["src/main/java/com/acme/ledger/LedgerEntry.java"],
    },
]


_RELATED_PRS = [
    {
        "number": 127,
        "title": "refactor(upi): simplify response handling",
        "author": _DEMO_AUTHOR,
        "url": "https://github.com/acme-demo/payment-service/pull/127",
        "merged_at": "2026-09-14T18:32:00Z",
        "files": [_DEMO_FILE],
        "relevance_score": 0.93,
        "reason": (
            "PR #127 modified the exact file src/main/java/com/acme/payment/"
            "PaymentProcessor.java at line 442. The refactor removed a null "
            "guard on upiResponse.getReferenceId(), directly causing the "
            "NullPointerException."
        ),
    },
    {
        "number": 125,
        "title": "feat(ledger): add idempotency key to entries",
        "author": "rahul.kumar",
        "url": "https://github.com/acme-demo/payment-service/pull/125",
        "merged_at": "2026-09-12T09:21:00Z",
        "files": ["src/main/java/com/acme/ledger/LedgerEntry.java"],
        "relevance_score": 0.44,
        "reason": (
            "PR #125 modified LedgerEntry, which is constructed at line 438 "
            "but does not touch the reference-id path at line 442. Related "
            "but unlikely the direct cause."
        ),
    },
]


# ── Mock service ─────────────────────────────────────────────────────────

class MockGitHubService:
    """Deterministic, network-free implementation of GitHubService."""

    def __init__(self):
        logger.info("🛠️  MockGitHubService initialized (DEMO_MODE)")

    async def get_recent_prs(self, repo_name: str, hours: int = 24) -> list:
        logger.debug(f"🛠️  [MOCK] get_recent_prs({repo_name}, hours={hours})")
        return [dict(pr) for pr in _RECENT_PRS]

    async def get_blame_with_pr(
        self, repo_name: str, file_path: str, line_number: int
    ) -> dict:
        logger.debug(
            f"🛠️  [MOCK] get_blame_with_pr({repo_name}, {file_path}:{line_number})"
        )
        return {
            "commit_hash": "a3f9d21c",
            "author": _DEMO_AUTHOR,
            "author_avatar": None,
            "message": "refactor(upi): simplify response handling",
            "line": line_number,
            "file": file_path,
            "pr_number": 127,
            "pr_title": "refactor(upi): simplify response handling",
            "pr_url": "https://github.com/acme-demo/payment-service/pull/127",
            "pr_author": _DEMO_AUTHOR,
            "contributors": [
                {
                    "username": _DEMO_AUTHOR,
                    "role": "author",
                    "avatar": None,
                    "url": None,
                },
                {
                    "username": "priya.singh",
                    "role": "reviewer",
                    "avatar": None,
                    "url": None,
                },
            ],
            "simulated": True,
        }

    async def get_related_prs(
        self, repo_name: str, file_path: str, line_number: int, limit: int = 5
    ) -> list:
        logger.debug(
            f"🛠️  [MOCK] get_related_prs({repo_name}, {file_path}:{line_number})"
        )
        return [dict(pr) for pr in _RELATED_PRS[:limit]]

    async def get_file_content(
        self,
        repo_name: str,
        file_path: str,
        line_number: int,
        context_lines: int = 5,
    ) -> dict:
        logger.debug(
            f"🛠️  [MOCK] get_file_content({repo_name}, {file_path}:{line_number})"
        )
        return {
            "file_path": file_path,
            "line_number": line_number,
            "total_lines": 612,
            "code_snippet": _CODE_SNIPPET,
            "full_file": None,
            "simulated": True,
        }
