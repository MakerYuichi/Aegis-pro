from dataclasses import dataclass, field
from typing import Literal, Optional


# Below this score, we mark the pick as low confidence. The threshold is
# deliberately generous — a docs-only repo will usually score around 1.0,
# a real production file will score 6+. The threshold splits those two.
_LOW_CONFIDENCE_THRESHOLD = 4.0

# Files above this size are unlikely to be a single-purpose handler and
# slow the demo down. Skip them entirely — they don't end up in the tree.
_MAX_FILE_BYTES = 200_000

# Approximate bytes-per-line for the size heuristic. Real files vary, but
# this is close enough to distinguish "helper" from "monolith".
_BYTES_PER_LINE = 40


# Directories that strongly suggest production code.
_CODE_DIRS = {
    "src": 3.0,
    "lib": 3.0,
    "internal": 3.0,
    "app": 2.5,
    "cmd": 2.0,
    "pkg": 2.0,
    "server": 2.0,
    "api": 2.0,
    "core": 2.0,
}

# Directories that strongly suggest teaching / non-production.
_DOC_DIRS = {
    "docs_src": -3.0,
    "docs": -3.0,
    "examples": -3.0,
    "example": -3.0,
    "samples": -3.0,
    "sample": -3.0,
    "tutorial": -3.0,
    "tutorials": -3.0,
    "demos": -3.0,
    "demo": -3.0,
    "playground": -3.0,
    "site": -2.0,
}

# Filename keywords that suggest the file *does something*.
_FILE_KEYWORDS = {
    "handler": 2.0,
    "service": 2.0,
    "controller": 2.0,
    "processor": 2.0,
    "dispatcher": 2.0,
    "worker": 2.0,
    "client": 2.0,
    "manager": 1.5,
    "router": 1.5,
    "middleware": 1.5,
    "server": 1.5,
    "engine": 1.5,
    "gateway": 1.5,
    "repository": 1.5,
    "serializer": 1.5,
}

# Filename keywords that suggest teaching / non-production.
_FILE_PENALTIES = {
    "tutorial": -2.0,
    "example": -2.0,
    "sample": -2.0,
    "demo": -2.0,
    "hello": -1.5,
}

# Domain keywords. These don't make a file "production" but they make
# the incident more relatable — a null access in auth/handler.py reads
# better than one in util.py.
_DOMAIN_KEYWORDS = {
    "auth": 1.5,
    "payment": 1.5,
    "checkout": 1.5,
    "order": 1.5,
    "user": 1.5,
    "account": 1.5,
    "billing": 1.5,
    "session": 1.5,
    "login": 1.5,
    "cart": 1.5,
    "customer": 1.5,
    "notification": 1.0,
    "message": 1.0,
    "cache": 1.0,
    "queue": 1.0,
    "search": 1.0,
}

_EXTENSIONS_BY_LANGUAGE = {
    "Python": {".py"},
    "Java": {".java", ".kt"},
    "Go": {".go"},
    "Node": {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"},
    "Rust": {".rs"},
}

_KNOWN_LANGUAGES = set(_EXTENSIONS_BY_LANGUAGE.keys())

# Extensions we consider "code". If the top candidate doesn't have one
# of these, we mark it fallback — the generator will synthesize the
# incident instead of binding to a real file.
_CODE_EXTENSIONS = {
    ".py", ".java", ".kt", ".go", ".rs", ".ts", ".tsx", ".js", ".jsx",
    ".mjs", ".cjs", ".rb", ".php", ".cs", ".cpp", ".c", ".h", ".swift",
    ".scala", ".ex", ".exs", ".clj", ".lua", ".pl",
}


@dataclass(frozen=True)
class FileCandidate:
    path: str
    score: float
    reasons: list[str] = field(default_factory=list)
    confidence: Literal["high", "low", "fallback"] = "high"


# ── Scoring helpers ────────────────────────────────────────────────────

def _extension(path: str) -> str:
    if "." not in path.rsplit("/", 1)[-1]:
        return ""
    return "." + path.rsplit(".", 1)[-1].lower()


def _segments(path: str) -> list[str]:
    return [p for p in path.split("/") if p]


def _score_directory(path: str) -> tuple[float, list[str]]:
    delta = 0.0
    reasons: list[str] = []
    segments = _segments(path)[:-1]  # ignore filename
    for seg in segments:
        seg_l = seg.lower()
        if seg_l in _CODE_DIRS:
            delta += _CODE_DIRS[seg_l]
            reasons.append(f"+{_CODE_DIRS[seg_l]:.1f} under {seg}/")
        if seg_l in _DOC_DIRS:
            delta += _DOC_DIRS[seg_l]
            reasons.append(f"{_DOC_DIRS[seg_l]:.1f} under {seg}/")
        if seg_l in ("tests", "test", "spec", "__tests__"):
            delta -= 2.0
            reasons.append("-2.0 under tests/")
        if seg_l in ("vendor", "generated", "third_party", "node_modules"):
            delta -= 2.0
            reasons.append(f"-2.0 under {seg}/")
    return delta, reasons


def _score_extension(path: str, language: str) -> tuple[float, list[str]]:
    ext = _extension(path)
    if not ext:
        return -2.0, ["no extension"]
    wanted = _EXTENSIONS_BY_LANGUAGE.get(language, set())
    if ext in wanted:
        return 2.5, [f"language match {ext}"]
    if language in _KNOWN_LANGUAGES:
        return -2.0, [f"language mismatch {ext} != {language}"]
    return 0.0, []


def _score_filename_keywords(path: str) -> tuple[float, list[str]]:
    name = path.rsplit("/", 1)[-1].lower()
    # Strip extension so 'handler.py' -> 'handler'
    stem = name.rsplit(".", 1)[0] if "." in name else name
    delta = 0.0
    reasons: list[str] = []
    for kw, weight in _FILE_KEYWORDS.items():
        if kw in stem:
            delta += weight
            reasons.append(f"+{weight:.1f} filename contains '{kw}'")
    for kw, weight in _FILE_PENALTIES.items():
        if kw in stem:
            delta += weight
            reasons.append(f"{weight:.1f} filename contains '{kw}'")
    return delta, reasons


def _score_domain_keywords(path: str) -> tuple[float, list[str]]:
    lowered = path.lower()
    delta = 0.0
    reasons: list[str] = []
    for kw, weight in _DOMAIN_KEYWORDS.items():
        if kw in lowered:
            delta += weight
            reasons.append(f"+{weight:.1f} path contains '{kw}'")
    return delta, reasons


def _score_size(size: int) -> tuple[float, list[str]]:
    if size <= 0:
        return -1.5, ["empty file"]
    approx_lines = size // _BYTES_PER_LINE
    if approx_lines < 20:
        return -1.5, [f"~{approx_lines} lines (too small)"]
    if approx_lines > 3000:
        return -1.0, [f"~{approx_lines} lines (likely generated or monolith)"]
    if 100 <= approx_lines <= 800:
        return 1.0, [f"~{approx_lines} lines (ideal size)"]
    return 0.0, [f"~{approx_lines} lines"]


def _score_path_extras(path: str) -> tuple[float, list[str]]:
    delta = 0.0
    reasons: list[str] = []
    lowered = path.lower()
    name = path.rsplit("/", 1)[-1].lower()

    # Generated file markers
    for marker in (".pb.go", ".g.cs", ".generated.", "_pb2.py"):
        if marker in name:
            delta -= 2.0
            reasons.append(f"-2.0 generated ({marker})")

    # Test file markers
    if name.startswith("test_") or name.startswith("test-") or name.endswith("_test.go"):
        delta -= 2.0
        reasons.append("-2.0 test file")
    if name.endswith(".test.ts") or name.endswith(".test.js") or name.endswith(".spec.ts"):
        delta -= 2.0
        reasons.append("-2.0 test file")

    # Docs
    if name.endswith(".md") or name.endswith(".rst") or name == "readme":
        delta -= 1.5
        reasons.append("-1.5 documentation file")

    # Config
    if name.endswith((".json", ".yaml", ".yml", ".toml", ".ini", ".env", ".lock")):
        delta -= 1.5
        reasons.append("-1.5 config file")

    return delta, reasons


def _score_depth_in_code_dir(path: str) -> tuple[float, list[str]]:
    """Files deeper in src/ or lib/ are more likely real business logic."""
    segments = _segments(path)
    for i, seg in enumerate(segments):
        if seg.lower() in ("src", "lib", "internal"):
            depth = len(segments) - i - 2  # -2 for the code dir and the filename
            bonus = min(max(depth, 0) * 0.5, 1.5)
            if bonus > 0:
                return bonus, [f"+{bonus:.1f} depth {depth} under {seg}/"]
    return 0.0, []


# ── Public entry point ─────────────────────────────────────────────────

def _score_candidate(path: str, size: int, language: str) -> FileCandidate:
    total = 0.0
    reasons: list[str] = []

    for scorer in (
        lambda p: _score_directory(p),
        lambda p: _score_extension(p, language),
        _score_filename_keywords,
        _score_domain_keywords,
        lambda p: _score_size(size),
        _score_path_extras,
        _score_depth_in_code_dir,
    ):
        delta, why = scorer(path)
        total += delta
        reasons.extend(why)

    confidence: Literal["high", "low"] = (
        "high" if total >= _LOW_CONFIDENCE_THRESHOLD else "low"
    )
    return FileCandidate(path=path, score=round(total, 3), reasons=reasons, confidence=confidence)


def select_target_files(
    tree: list[dict],
    language: str,
    limit: int = 5,
) -> list[FileCandidate]:
    """
    Return up to `limit` top-scoring file candidates, sorted by score desc.

    Filters out `fallback`-confidence candidates (non-code files like
    READMEs and configs) so the dropdown only shows real code. If every
    candidate is fallback, returns the single best one anyway so the
    caller can surface "not_code".

    Never raises. Returns [] for empty or blob-less trees.
    """
    if not tree:
        return []

    candidates: list[FileCandidate] = []
    for item in tree:
        if item.get("type") != "blob":
            continue
        path = item.get("path") or ""
        if not path:
            continue
        size = int(item.get("size") or 0)
        if size > _MAX_FILE_BYTES:
            continue
        candidates.append(_score_candidate(path, size, language))

    if not candidates:
        return []

    candidates.sort(key=lambda c: (-c.score, len(c.path), c.path))

    # Partition into code and fallback picks.
    code: list[FileCandidate] = []
    fallback: list[FileCandidate] = []
    for c in candidates:
        ext = _extension(c.path)
        if ext in _CODE_EXTENSIONS:
            code.append(c)
        else:
            # Rebuild with the fallback confidence so the reasons list
            # stays accurate.
            fallback.append(FileCandidate(
                path=c.path,
                score=c.score,
                reasons=c.reasons + ["no code extension — incident will be synthesized"],
                confidence="fallback",
            ))

    if code:
        return code[:limit]

    # No code file at all — return the single best non-code pick so the
    # caller can return a "not_code" error with the path attached.
    return fallback[:1]


def select_target_file(
    tree: list[dict],
    language: str,
) -> Optional[FileCandidate]:
    """
    Return the single best candidate, or None for an empty tree.

    Thin wrapper around select_target_files. Kept for callers that don't
    need the full list. Same behavior as before: never returns None for
    a non-empty tree.
    """
    picks = select_target_files(tree, language, limit=1)
    return picks[0] if picks else None


def score_one_file(path: str, size: int, language: str) -> FileCandidate:
    """
    Score a single file path. Public wrapper around _score_candidate.
    Used by the endpoint when a specific file is forced and isn't in the
    top-N candidates.
    """
    return _score_candidate(path, size, language)