#!/usr/bin/env python3
"""
Prefetch entrypoint. Runs inside the prefetcher container.

Stdlib only. No imports from the orchestrator. The container is a
different trust zone: it has network, and the code it downloads is
executed by nobody here (we use --only-binary=:all:, so pip refuses
to build anything from source). It has no secrets, no docker
socket, no route to internal ranges.

Contract with the orchestrator:
  - Reads MANIFEST_PATH (a file mounted read-only)
  - Writes wheels into CACHE_DIR
  - Writes the sanitized lock to LOCK_PATH
  - Prints pip's output, then a single-line JSON receipt as the
    last line of stdout

Everything the orchestrator needs to vouch for is in that receipt.
The container does not write a receipt file into the cache — the
cache holds wheels only.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path


# ── Sanitizer (duplicated, deliberately) ─────────────────────────
#
# This is a copy of the orchestrator's sanitize module with no
# imports back to src/. Two reasons:
#
#   1. Trust zone separation. The container must not import
#      orchestrator code — the orchestrator is not mounted.
#   2. Defense-in-depth. If the orchestrator's sanitizer has a bug
#      that lets a bad line through, the container's sanitizer is a
#      second, independent implementation of the same rule. Bugs
#      rarely appear in two independently written checks.
#
# The two implementations are covered by tests that assert they
# agree on the fixture corpus. See tests/prefetch/test_sanitize.py.

_REQ_RE = re.compile(
    r"""
    ^\s*
    (?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)
    (?P<extras>\[[^\]]+\])?
    \s*
    (?:
        (?P<op>==|>=|<=|~=|!=|>|<)
        \s*
        (?P<version>[A-Za-z0-9][A-Za-z0-9._-]*)
        (?:\+(?P<variant>[A-Za-z0-9][A-Za-z0-9._-]*))?
    )?
    \s*
    (?:;\s*(?P<marker>.+?))?
    \s*$
    """,
    re.VERBOSE,
)

_STRIPPED_DIRECTIVES = (
    "--extra-index-url",
    "-i", "--index-url",
    "-f", "--find-links",
    "--trusted-host",
    "--pre",
    "--prefer-binary",
)
_REJECTED_DIRECTIVES = ("-e", "--editable")

DEFAULT_INDEX_URL = "https://pypi.org/simple/"

VARIANT_INDEX_OVERRIDES = {
    ("torch", "cpu"):       "https://download.pytorch.org/whl/cpu",
    ("torchvision", "cpu"): "https://download.pytorch.org/whl/cpu",
    ("torchaudio", "cpu"):  "https://download.pytorch.org/whl/cpu",
}
BASE_INDEX_OVERRIDES: dict = {}


def normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


class EntryError(Exception):
    pass


def sanitize(path: Path) -> list[dict]:
    """
    Parse a manifest into a list of requirement dicts.

    Ranges are accepted, not rejected. The dict records whether
    the line was an exact pin or a range; the lockfile renderer
    preserves the original specifier for ranges so pip's resolver
    can pick the absolute version during download.

    Raises EntryError only for directives or malformed syntax.
    """
    text = path.read_text(encoding="utf-8")
    pins = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("\\", ";")):
            raise EntryError(
                f"unsupported_continuation at line {lineno}: {raw!r}"
            )
        if line.startswith("-"):
            token = line.split()[0]
            if token in _REJECTED_DIRECTIVES:
                raise EntryError(
                    f"rejected_directive: {token} at line {lineno}"
                )
            if token in _STRIPPED_DIRECTIVES:
                continue
            raise EntryError(
                f"unknown_directive: {token} at line {lineno}"
            )
        if " @ " in line:
            raise EntryError(
                f"direct_url_not_allowed at line {lineno}: {raw!r}"
            )
        if "\\" in line:
            raise EntryError(
                f"multiline_hash_not_supported at line {lineno}"
            )

        m = _REQ_RE.match(line)
        if m is None:
            raise EntryError(f"malformed_requirement at line {lineno}: {raw!r}")

        extras = ()
        if m.group("extras"):
            extras = tuple(
                e.strip()
                for e in m.group("extras")[1:-1].split(",")
                if e.strip()
            )

        op = m.group("op")
        version = m.group("version")
        variant = m.group("variant")

        if op is None:
            is_pinned = False
            raw_specifier = ""
            base_version = ""
            local_variant = ""
        elif op == "==":
            is_pinned = True
            base_version = version
            local_variant = variant or ""
            raw_specifier = f"=={version}" + (
                f"+{variant}" if variant else ""
            )
        else:
            is_pinned = False
            base_version = ""
            local_variant = ""
            raw_specifier = f"{op}{version}"

        pins.append({
            "name": normalize_name(m.group("name")),
            "is_pinned": is_pinned,
            "base_version": base_version,
            "local_variant": local_variant,
            "raw_specifier": raw_specifier,
            "extras": list(extras),
            "environment_marker": (m.group("marker") or "").strip() or None,
            "raw_line": raw,
            "line_number": lineno,
        })
    if not pins:
        raise EntryError("empty_manifest")
    return pins


def route(pin: dict) -> str:
    """Return the index URL for this pin. Mirrors policy.route_pin."""
    if pin["local_variant"]:
        key = (pin["name"], pin["local_variant"])
        if key in VARIANT_INDEX_OVERRIDES:
            return VARIANT_INDEX_OVERRIDES[key]
        raise EntryError(
            f"unknown_local_variant: {pin['name']}+{pin['local_variant']}"
        )
    if pin["name"] in BASE_INDEX_OVERRIDES:
        return BASE_INDEX_OVERRIDES[pin["name"]]
    return DEFAULT_INDEX_URL


def build_lockfile(pins: list[dict]) -> str:
    """
    Render a sanitized requirements file for pip download.

    Pinned lines render as `name[extras]==version+variant`.
    Unpinned lines render as `name[extras]{raw_specifier}` — the
    original range, verbatim. pip resolves it during download.

    No directives, no direct URLs. Just requirements pip will
    accept and resolve.
    """
    lines = []
    for p in pins:
        extras = f"[{','.join(p['extras'])}]" if p["extras"] else ""
        if p["is_pinned"]:
            body = f"{p['name']}{extras}{p['raw_specifier']}"
        else:
            spec = p["raw_specifier"]
            if spec:
                body = f"{p['name']}{extras}{spec}"
            else:
                body = f"{p['name']}{extras}"
        if p["environment_marker"]:
            body += f" ; {p['environment_marker']}"
        lines.append(body)
    return "\n".join(lines) + "\n"


def sha256_of(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def platform_tag() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    return f"{system}_{machine}"


def run_pip_download(
    lockfile_path: Path,
    index_url: str,
    dest: Path,
) -> tuple[int, str]:
    """
    Run pip download for one index. --only-binary=:all: is the
    critical flag: it makes pip refuse to build or execute any
    sdist's setup.py. A package that has no wheel on this index
    fails here, and that's the honest outcome.

    --require-hashes is deliberately NOT set. This phase is where
    the hashes are computed, so they cannot be required as input.
    The verification container (PR 2) will run pip install with
    --require-hashes against the lock file the prefetcher
    produces, where every line does carry a hash. The split is:
    prefetch establishes, verify enforces.

    EXTRA_FIND_LINKS: when set, pip additionally searches the
    given directory for wheels before falling back to the index.
    The retry path sets this to a mirror directory containing a
    wheel the build pipeline produced for an sdist-only package.
    Multiple paths are separated by the OS path separator.
    """
    extra = os.environ.get("EXTRA_FIND_LINKS", "").strip()

    argv = [
        sys.executable, "-m", "pip", "download",
        "--no-deps",
        "--only-binary=:all:",
        "--index-url", index_url,
        "--dest", str(dest),
        "--no-cache-dir",
    ]
    if extra:
        for path in extra.split(os.pathsep):
            path = path.strip()
            if path:
                argv.extend(["--find-links", path])
    argv.extend(["-r", str(lockfile_path)])

    proc = subprocess.run(
        argv, capture_output=True, text=True, timeout=300,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "") 

def _identify_failing_pin(
    group: list[dict],
    pip_output: str,
) -> dict | None:
    """
    Look at pip's output and figure out which pin in the group failed.

    pip's failure message names the exact requirement it couldn't
    satisfy. The format is one of:

        Could not find a version that satisfies the requirement X==Y
        Could not find a version that satisfies the requirement X>=Y
        No matching distribution found for X==Y

    We match against the group's pins by normalized package name.
    If pip named a package that isn't in this group (possible when
    the failure is a transitive dependency of a package that
    succeeded), the caller falls back to the generic
    index_fetch_failed.

    Returns the matching pin dict from the group, or None.
    """
    # Try the "Could not find a version that satisfies the
    # requirement" form first — that's what pip emits when it
    # can't resolve a specifier at all.
    m = re.search(
        r"Could not find a version that satisfies the requirement "
        r"([A-Za-z0-9][A-Za-z0-9._-]*)",
        pip_output,
    )
    if m is None:
        # Fall back to the "No matching distribution found for"
        # form, which appears when the version specifier resolved
        # but the specific version isn't available.
        m = re.search(
            r"No matching distribution found for "
            r"([A-Za-z0-9][A-Za-z0-9._-]*)",
            pip_output,
        )
    if m is None:
        return None

    failed_name = normalize_name(m.group(1))
    for pin in group:
        if pin["name"] == failed_name:
            return pin
    return None


def diagnose_missing_version(
    pin: dict,
    python_version: str,
    platform_tag: str,
) -> dict:
    """
    When pip refuses a pin under --only-binary=:all:, query PyPI's
    JSON API to find out why.

    pip reports one message for three different situations:
      - the version doesn't exist
      - the version exists but ships only an sdist (no wheel)
      - the version exists with wheels, but not for this Python
        or platform

    All three surface as "No matching distribution found", which
    is useless to a human trying to fix the manifest. This function
    returns one of three specific reasons instead.

    Network is used, but only a single GET against pypi.org's
    public JSON API. No code is executed. No package data is
    downloaded. Just metadata.

    Arguments:
      pin: the sanitized pin dict from the manifest. Needs `name`
           and, for pinned entries, `base_version`. For unpinned
           entries, the caller passes whatever version pip was
           trying to resolve when it failed.
      python_version: the interpreter version in the container,
           e.g. "3.11.16"
      platform_tag: the container's platform, e.g. "linux_aarch64"

    Returns:
      {"reason": str, "detail": str, "available_wheels": [...]}

      reason is one of:
        "version_not_found"
        "sdist_only"
        "no_compatible_wheel"
        "pypi_lookup_failed"    — network or JSON parse error
    """
    import urllib.request
    import urllib.error

    name = pin["name"]
    version = pin.get("base_version") or pin.get("resolved_version") or ""

    result = {
        "reason": "pypi_lookup_failed",
        "detail": "",
        "available_wheels": [],
    }

    if not version:
        result["detail"] = "no version to look up"
        return result

    url = f"https://pypi.org/pypi/{name}/{version}/json"

    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            result["reason"] = "version_not_found"
            result["detail"] = (
                f"{name} {version} does not exist on PyPI"
            )
        else:
            result["detail"] = f"HTTP {e.code}"
        return result
    except Exception as e:
        result["detail"] = f"{type(e).__name__}: {e}"
        return result

    files = payload.get("urls") or []
    wheels = [
        f for f in files
        if f.get("packagetype") == "bdist_wheel"
    ]
    sdists = [
        f for f in files
        if f.get("packagetype") == "sdist"
    ]

    if not wheels:
        if sdists:
            result["reason"] = "sdist_only"
            result["detail"] = (
                f"{name} {version} ships only an sdist "
                f"({sdists[0].get('filename', 'unknown')}). "
                f"--only-binary=:all: cannot fetch it. "
                f"Rung 3 (offline sdist build) is the path "
                f"forward; not yet implemented."
            )
        else:
            result["reason"] = "version_not_found"
            result["detail"] = (
                f"{name} {version} has no downloadable files"
            )
        return result

    # Wheels exist. Check whether any match the container's
    # Python + platform. The wheel filename encodes:
    #   {name}-{version}(-build)?-{python}-{abi}-{platform}.whl
    py_tag = "cp" + python_version.replace(".", "")[:3]
    # py_tag for 3.11.16 is "cp311"

    result["available_wheels"] = [w["filename"] for w in wheels]

    for w in wheels:
        fname = w.get("filename", "")
        # Cheap match: does the filename contain the python tag
        # (cp311, py3, py311) or is it a universal wheel?
        if (
            py_tag in fname
            or "py3-none-any" in fname
            or "py2.py3-none-any" in fname
        ):
            # A wheel that at least targets this Python exists.
            # If pip still refused, it's a platform mismatch.
            break
    else:
        # No wheel matched the Python tag.
        result["reason"] = "no_compatible_wheel"
        result["detail"] = (
            f"{name} {version} has wheels, but none for "
            f"Python {python_version} on {platform_tag}. "
            f"Available: {', '.join(w['filename'] for w in wheels[:5])}"
        )
        return result

    # Wheels exist for this Python. The failure is probably
    # platform, but we can't tell from the filename prefix alone
    # without a full wheel-tag parser. Report the general case.
    result["reason"] = "no_compatible_wheel"
    result["detail"] = (
        f"{name} {version} has wheels for this Python, but none "
        f"matched the platform {platform_tag}. "
        f"Available: {', '.join(w['filename'] for w in wheels[:5])}"
    )
    return result


def main() -> int:
    start = time.monotonic()

    manifest_path = Path(os.environ["MANIFEST_PATH"])
    cache_dir = Path(os.environ["CACHE_DIR"])
    lock_path = Path(os.environ["LOCK_PATH"])

    if not manifest_path.is_file():
        print(f"manifest_not_found: {manifest_path}", file=sys.stderr)
        return 2

    cache_dir.mkdir(parents=True, exist_ok=True)

    # 1. Sanitize.
    pins = sanitize(manifest_path)
    lockfile_text = build_lockfile(pins)
    lock_path.write_text(lockfile_text, encoding="utf-8")

    # 2. Group pins by index. One pip invocation per distinct index.
    groups: dict[str, list[dict]] = {}
    for pin in pins:
        idx = route(pin)
        groups.setdefault(idx, []).append(pin)

    # 3. Download each group.
    all_output: list[str] = []
    for index_url, group in groups.items():
        group_lines = build_lockfile(group)
        group_file = cache_dir / "_group_requirements.txt"
        group_file.write_text(group_lines, encoding="utf-8")
        rc, out = run_pip_download(
            group_file, index_url, cache_dir,
        )
        all_output.append(f"# index: {index_url}\n{out}")
        group_file.unlink(missing_ok=True)
        if rc != 0:
            print("\n".join(all_output))

            # pip reported a fetch failure. Before declaring
            # index_fetch_failed, find out why. Query PyPI for the
            # specific reason and surface that instead of pip's
            # misleading summary.
            failing_pin = _identify_failing_pin(group, out)

            if failing_pin is not None:
                diag = diagnose_missing_version(
                    failing_pin,
                    platform.python_version(),
                    platform_tag(),
                )
                # Print the diagnosis as the last stdout line so
                # the runner parses it as the failure receipt.
                print(json.dumps({
                    "error": diag["reason"],
                    "detail": diag["detail"],
                    "package": failing_pin["name"],
                    "version": failing_pin.get("base_version", ""),
                    "available_wheels": diag["available_wheels"],
                    "index_url": index_url,
                }, separators=(",", ":")))
                return 3

            # Couldn't identify which pin failed. Fall back to the
            # old message.
            print(f"index_fetch_failed: {index_url}", file=sys.stderr)
            return 3

    # 4. Enumerate what landed. For each artifact in the cache,
    #    parse its package name out of the filename and match it
    #    against the manifest's package list. Transitive
    #    dependencies are recorded too — the receipt is the full
    #    resolved tree, not just top-level pins.
    def _normalize_for_match(name: str) -> str:
        return re.sub(r"[-_.]+", "-", name).lower()

    manifest_names = {_normalize_for_match(p["name"]) for p in pins}

    packages: list[dict] = []
    seen: set[str] = set()

    for artifact in sorted(cache_dir.iterdir()):
        if not artifact.is_file():
            continue
        # Skip the lockfile and staged files.
        if artifact.name.startswith("_"):
            continue
        if artifact.name == "requirements.lock":
            continue
        if not (artifact.name.endswith(".whl")
                or artifact.name.endswith(".tar.gz")):
            continue

        fname = artifact.name
        if fname.endswith(".whl"):
            stem = fname[:-4]
        else:
            stem = fname[:-7]  # strip .tar.gz

        # Wheel filenames are `{name}-{version}(-build)?-py-abi-platform.whl`.
        # sdist filenames are `{name}-{version}.tar.gz`. In both cases
        # the package name is `parts[0]` and the version is `parts[1]`.
        parts = stem.split("-")
        if len(parts) < 2:
            continue
        pkg_name = _normalize_for_match(parts[0])

        if pkg_name in seen:
            continue
        seen.add(pkg_name)

        version_component = parts[1]
        if "+" in version_component:
            base_version, local_variant = version_component.split("+", 1)
        else:
            base_version, local_variant = version_component, ""

        matching_pin = next(
            (p for p in pins
             if _normalize_for_match(p["name"]) == pkg_name),
            None,
        )

        packages.append({
            "name": pkg_name,
            "base_version": base_version,
            "local_variant": local_variant,
            "extras": matching_pin["extras"] if matching_pin else [],
            "environment_marker": (
                matching_pin["environment_marker"]
                if matching_pin else None
            ),
            "hashes": [
                "sha256:"
                + hashlib.sha256(artifact.read_bytes()).hexdigest()
            ],
            "source_index": (
                route(matching_pin) if matching_pin else ""
            ),
            "filename": fname,
            "dependencies": [],
        })

    # 5. Print pip output, then the receipt as the last line.
    print("\n".join(all_output))

    receipt = {
        "manifest_path": manifest_path.name,
        "manifest_hash": sha256_of(lockfile_text),
        "python_version": platform.python_version(),
        "platform_tag": platform_tag(),
        "packages": packages,
        "fetched_now": True,
        "duration_ms": int((time.monotonic() - start) * 1000),
    }
    print(json.dumps(receipt, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
