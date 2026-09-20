from dataclasses import dataclass
from typing import Optional
import re


SUPPORTED_HOSTS = ("github.com", "gitlab.com", "bitbucket.org")

# Hosts whose presence in the string should make us reject early with a
# specific reason, rather than trying to guess.
_KNOWN_UNSUPPORTED = (
    "gitea.com",
    "codeberg.org",
    "sourceforge.net",
    "bitbucket.io",
    "git.sr.ht",
)

# Identifier shape for org and repo names. GitHub/GitLab/Bitbucket allow
# letters, digits, dashes, underscores, dots. We do not enforce the maximum
# lengths — the backend doesn't care.
_IDENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# Language inference keywords. Order matters: more specific first.
_LANGUAGE_KEYWORDS = [
    ("go", "Go"),
    ("golang", "Go"),
    ("py", "Python"),
    ("python", "Python"),
    ("django", "Python"),
    ("flask", "Python"),
    ("fastapi", "Python"),
    ("java", "Java"),
    ("spring", "Java"),
    ("jvm", "Java"),
    ("node", "Node"),
    ("nodejs", "Node"),
    ("next", "Node"),
    ("typescript", "Node"),
    ("ts", "Node"),
    ("js", "Node"),
    ("javascript", "Node"),
    ("rust", "Rust"),
    ("cargo", "Rust"),
]


@dataclass(frozen=True)
class ParseResult:
    ok: bool
    host: Optional[str] = None
    org: Optional[str] = None
    repo: Optional[str] = None
    language_hint: str = "Java"  # default language
    reason: Optional[str] = None
    detail: Optional[str] = None


def _fail(reason: str, detail: str) -> ParseResult:
    return ParseResult(ok=False, reason=reason, detail=detail)


def _infer_language(text: str) -> str:
    lowered = text.lower()
    for keyword, language in _LANGUAGE_KEYWORDS:
        # Require a word boundary on the left so 'ts' doesn't match 'tests'
        if re.search(rf"(^|[^a-z]){re.escape(keyword)}([^a-z]|$)", lowered):
            return language
    return "Java"


def _extract_host_and_path(raw: str) -> tuple[str, str]:
    """
    Return (host_lowercase_or_empty, path_without_leading_slash).

    Handles:
      https://host/org/repo(.git)
      http://host/org/repo
      git@host:org/repo(.git)
      host/org/repo
      org/repo  (no host — returns ('', 'org/repo'))
    """
    s = raw.strip()

    # SSH form: git@github.com:org/repo.git
    ssh = re.match(r"^[a-zA-Z0-9._-]{0,64}@([A-Za-z0-9.-]{0,255}):(.{0,4096})$", s)
    if ssh:
        return ssh.group(1).lower(), ssh.group(2)

    # URL form with scheme
    url = re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]{0,63}://([A-Za-z0-9.-]{0,255})/?(.*)$", s)
    if url:
        return url.group(1).lower(), url.group(2)

    # Bare host/path or org/repo — no scheme, no user@
    if "/" in s:
        first, rest = s.split("/", 1)
        if "." in first:
            return first.lower(), rest
        return "", s

    return "", s


def _strip_git_suffix(repo: str) -> str:
    return repo[:-4] if repo.endswith(".git") else repo


def parse_repo_input(raw: str) -> ParseResult:
    if raw is None or not raw.strip():
        return _fail("empty", "Input was blank. Paste a repo URL or an org/repo pair.")

    s = raw.strip()

    # Reject strings that are obviously not repo references before we try
    # to parse them. Keeps error messages specific.
    if " " in s:
        return _fail("malformed", "Input contains spaces. Paste a single repo reference.")

    host, path = _extract_host_and_path(s)

    if host:
        # The host exists in the input — check allowlist.
        if host in _KNOWN_UNSUPPORTED:
            return _fail(
                "unsupported_host",
                f"Host '{host}' is not supported. Supported: {', '.join(SUPPORTED_HOSTS)}.",
            )
        if host not in SUPPORTED_HOSTS:
            # A '.' in the "host" position means someone typed something that
            # looks like a host but isn't ours. Reject specifically.
            if "." in host:
                return _fail(
                    "unsupported_host",
                    f"Host '{host}' is not supported. Supported: {', '.join(SUPPORTED_HOSTS)}.",
                )
            # Otherwise the "host" was actually part of the path (e.g. 'org.repo/name').
            # Put it back and treat the whole thing as org/repo below.
            path = f"{host}/{path}"
            host = ""

    # At this point, path is either 'org/repo' or just 'repo' or empty.
    parts = [p for p in path.split("/") if p]

    if host:
        # We had a valid host in the input — require org/repo after it.
        if len(parts) < 2:
            return _fail(
                "missing_repo",
                f"Expected '<org>/<repo>' after '{host}'. Got: {path or '(nothing)'}.",
            )
    else:
        # No host at all — require at least 'org/repo'.
        if len(parts) < 2:
            return _fail(
                "too_short",
                "Expected '<org>/<repo>' or a full URL. Got: " + (s or "(nothing)"),
            )

    org = parts[-2]
    repo = _strip_git_suffix(parts[-1])

    if not _IDENT_RE.match(org):
        return _fail(
            "malformed",
            f"Organization '{org}' contains invalid characters.",
        )
    if not _IDENT_RE.match(repo):
        return _fail(
            "malformed",
            f"Repository '{repo}' contains invalid characters.",
        )

    language = _infer_language(f"{org}/{repo}")

    return ParseResult(
        ok=True,
        host=host or "github.com",  # default for display when the input was org/repo
        org=org,
        repo=repo,
        language_hint=language,
    )


def supported_shapes() -> list[str]:
    """Return the list of accepted input shapes, for UI display on errors."""
    return [
        "https://github.com/org/repo",
        "https://github.com/org/repo.git",
        "git@github.com:org/repo.git",
        "github.com/org/repo",
        "org/repo",
        "https://gitlab.com/group/project",
        "https://bitbucket.org/team/repo",
    ]
