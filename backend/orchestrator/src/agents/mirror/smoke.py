"""
Smoke test for a freshly built wheel.

Called between build and publish. Validates the wheel against
the pin it was built to satisfy, so a build container that
produced a suspicious artifact (wrong name, wrong version, an
unlisted `.pth` that runs code at every interpreter start, a
zip bomb, a truncated RECORD) is refused before the mirror
carries it.

Four checks, in order of cost:

  1. Structural (fast, no container):
       - Wheel filename parses via packaging.utils
       - Filename's name and version match the pin
       - Exactly one .dist-info directory in the zip
       - .dist-info name matches the filename
       - METADATA's Name and Version match the pin
       - WHEEL's Tag: lines are a subset of the filename tags
       - RECORD is bidirectionally consistent with the zip
         (every member in RECORD, every RECORD entry hashes
         correctly; only RECORD and its signature files may
         have empty hashes; `.pth` import lines refused)

  2. Tag compatibility (fast, uses cached preflight tags):
       - Filename's tag set intersects the verifier's supported
         tags. A wheel tagged for cp312-manylinux_x86_64 on a
         cp311-aarch64 verifier is refused before the container
         tries to install it.

  3. Container import (slower, one `docker run`):
       - Install the wheel with --no-index --no-deps --target
         into a tmpfs
       - find_spec each top-level module
       - Refuse if any module isn't findable

A failed smoke test raises SmokeError with a specific reason,
which `integrate.py` converts to `smoke_failed: <reason>`.

Why these checks and not more:

  - RECORD proves internal consistency, not integrity. The
    builder controls both the files and their hashes; a
    malicious build produces a perfectly consistent wheel.
    The defenses against malice are the sdist-hash keying
    (writer.py), the builder's isolation (build.py), and the
    name binding (below). RECORD catches corruption, not
    attack.

  - The name binding is what makes an evil wheel refuse
    publishable: a wheel built from `sentence-transformers
    2.2.2` whose METADATA says `evil 1.0.0` fails the pin
    check, and a wheel whose filename says `sentence-
    transformers 2.2.2` but whose METADATA says `sentence-
    transformers 2.2.3` fails it too. Both are shadowing
    attacks; both refuse.

  - The tag check is the difference between "pip rejects the
    wheel and we report an install failure" and "we refuse
    the wheel and name the incompatibility." The former
    requires reading pip's output; the latter is a single
    named reason.
"""
from __future__ import annotations

import asyncio
import base64
import csv
import hashlib
import io
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path

from loguru import logger
from packaging.utils import (
    InvalidWheelFilename,
    canonicalize_name,
    parse_wheel_filename,
)

from src.agents.mirror.preflight import (
    PreflightError,
    get_supported_tags,
)
from src.config import settings


class SmokeError(Exception):
    """A built wheel failed validation. Never raised for
    infrastructure failure — those become BuildError or
    PreflightError upstream. Every SmokeError has a specific
    `reason` string that names which check refused the wheel."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


# Cap on the size of a wheel that gets smoke-tested. Same bound
# as the build container's output validation; the smoke test
# never sees a wheel that's already been refused there, but
# defensive redundancy costs nothing.
MAX_WHEEL_BYTES = 200 * 1024 * 1024

# Cap on the total decompressed size when reading RECORD and
# hashing members. A wheel that decompresses past this fails the
# smoke test rather than exhausting the orchestrator.
MAX_DECOMPRESSED_BYTES = 500 * 1024 * 1024

# Cap on the number of entries in RECORD.
MAX_RECORD_ENTRIES = 100_000


@dataclass(frozen=True)
class RecordEntry:
    path: str
    hash_alg: str  # "sha256", "md5", "sha1", or "" for empty
    hash_value: str  # urlsafe-base64, no padding; empty for empty


async def smoke_test(
    *,
    wheel_container_path: Path,
    wheel_host_path: Path,
    expected_name: str,
    expected_version: str,
) -> None:
    """
    Validate a built wheel before publishing it.

    wheel_container_path is the path THIS process reads the
    wheel from. wheel_host_path is the same wheel as the Docker
    daemon sees it (needed for the container import check).

    Raises SmokeError with a specific reason on any failure.
    """
    # 1. Structural checks (fast, no container).
    _check_size(wheel_container_path)
    filename_info = _parse_filename(wheel_container_path.name)
    _check_pin_match(
        filename_info, expected_name, expected_version,
        source="filename",
    )

    with zipfile.ZipFile(wheel_container_path) as zf:
        dist_info = _find_dist_info(zf, filename_info)
        _check_dist_info_name(dist_info, filename_info)
        _check_metadata(zf, dist_info, expected_name, expected_version)
        _check_wheel_tags(zf, dist_info, filename_info)
        entries = _parse_record(zf, dist_info)
        _verify_record_bidirectional(zf, entries)
        _check_pth_files(zf)
        top_modules = _top_level_modules_from_record(entries)

    if not top_modules:
        raise SmokeError(
            "no_top_level_modules",
            f"{wheel_container_path.name} declares no importable "
            f"top-level modules in RECORD",
        )

    # 2. Tag compatibility (fast, uses cached preflight tags).
    await _check_tag_compatibility(filename_info)

    # 3. Container import check (slow).
    await _check_imports(
        wheel_host_path=wheel_host_path,
        top_modules=top_modules,
        expected_name=expected_name,
    )

    logger.info(
        f"smoke_test: {wheel_container_path.name} passed "
        f"({len(top_modules)} top-level modules)"
    )


# ── structural checks ──────────────────────────────────────────

def _check_size(wheel_path: Path) -> None:
    st = wheel_path.stat()
    if st.st_size > MAX_WHEEL_BYTES:
        raise SmokeError(
            "wheel_too_large",
            f"{st.st_size} > {MAX_WHEEL_BYTES}",
        )
    if st.st_size == 0:
        raise SmokeError("wheel_empty", str(wheel_path))


def _parse_filename(filename: str):
    """Parse a wheel filename into (name, version, tags, build).

    packaging.utils.parse_wheel_filename raises
    InvalidWheelFilename for names that don't match PEP 427.
    """
    try:
        return parse_wheel_filename(filename)
    except InvalidWheelFilename as e:
        raise SmokeError(
            "invalid_filename", f"{filename}: {e}",
        ) from e


def _check_pin_match(filename_info, expected_name, expected_version, *, source):
    name, version, _build, _tags = filename_info
    canon_expected = canonicalize_name(expected_name)
    canon_actual = canonicalize_name(name)
    if canon_actual != canon_expected:
        raise SmokeError(
            "pin_name_mismatch",
            f"{source}: expected {canon_expected}, got {canon_actual}",
        )
    if str(version) != str(expected_version):
        raise SmokeError(
            "pin_version_mismatch",
            f"{source}: expected {expected_version}, got {version}",
        )


def _find_dist_info(zf: zipfile.ZipFile, filename_info) -> str:
    """Return the single .dist-info directory name in the wheel.

    Exactly one is required. Two .dist-info directories in one
    wheel is a confusion attack — different tools pick different
    ones, so the wheel's metadata is ambiguous.
    """
    candidates = {
        name.split("/")[0]
        for name in zf.namelist()
        if name.split("/")[0].endswith(".dist-info")
    }
    if len(candidates) == 0:
        raise SmokeError(
            "no_dist_info",
            f"{zf.filename}: no .dist-info directory",
        )
    if len(candidates) > 1:
        raise SmokeError(
            "multiple_dist_info",
            f"{sorted(candidates)}",
        )
    return candidates.pop()


def _check_dist_info_name(dist_info: str, filename_info) -> None:
    """The .dist-info directory name must match the filename's
    name and version. Mismatch = shadowing attack."""
    name, version, _build, _tags = filename_info
    # dist-info dirs are named <name>-<version>.dist-info where
    # name uses PEP 503 normalization but may include underscores.
    stem = dist_info.removesuffix(".dist-info")
    if "-" not in stem:
        raise SmokeError(
            "dist_info_malformed", dist_info,
        )
    di_name, di_version = stem.rsplit("-", 1)
    if canonicalize_name(di_name) != canonicalize_name(name):
        raise SmokeError(
            "dist_info_name_mismatch",
            f"filename={name}, dist-info={di_name}",
        )
    if di_version != str(version):
        raise SmokeError(
            "dist_info_version_mismatch",
            f"filename={version}, dist-info={di_version}",
        )


def _check_metadata(
    zf: zipfile.ZipFile, dist_info: str,
    expected_name: str, expected_version: str,
) -> None:
    """Parse METADATA and require Name and Version to match the pin."""
    meta_path = f"{dist_info}/METADATA"
    try:
        raw = zf.read(meta_path)
    except KeyError as e:
        raise SmokeError(
            "no_metadata", meta_path,
        ) from e
    if len(raw) > 1024 * 1024:
        raise SmokeError("metadata_too_large", str(len(raw)))

    meta: dict[str, str] = {}
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if not line:
            break
        if line.startswith((" ", "\t")):
            continue  # continuation
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip().lower()] = value.strip()

    meta_name = meta.get("name")
    meta_version = meta.get("version")
    if not meta_name or not meta_version:
        raise SmokeError(
            "metadata_malformed",
            f"Name={meta_name!r} Version={meta_version!r}",
        )
    if canonicalize_name(meta_name) != canonicalize_name(expected_name):
        raise SmokeError(
            "metadata_name_mismatch",
            f"expected {canonicalize_name(expected_name)}, "
            f"got {canonicalize_name(meta_name)}",
        )
    if meta_version != expected_version:
        raise SmokeError(
            "metadata_version_mismatch",
            f"expected {expected_version}, got {meta_version}",
        )


def _check_wheel_tags(zf: zipfile.ZipFile, dist_info: str, filename_info) -> None:
    """WHEEL's Tag: lines must be a subset of the filename's tags.

    pip trusts the filename alone. A wheel whose filename says
    cp311-manylinux_aarch64 but whose WHEEL says
    cp312-manylinux_x86_64 would install on the wrong Python if
    pip ever read WHEEL — it doesn't, but a downstream tool
    might. Comparing here catches the discrepancy cheaply.
    """
    _name, _version, _build, filename_tags = filename_info
    wheel_path = f"{dist_info}/WHEEL"
    try:
        raw = zf.read(wheel_path)
    except KeyError:
        raise SmokeError(
            "no_wheel_metadata", wheel_path,
        )
    if len(raw) > 64 * 1024:
        raise SmokeError("wheel_metadata_too_large", str(len(raw)))

    declared: set[str] = set()
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if line.lower().startswith("tag:"):
            value = line.split(":", 1)[1].strip()
            declared.add(value)
    if not declared:
        # Some wheels omit Tag: lines. That's a spec violation
        # but not an attack. Refuse rather than silently
        # accepting a wheel that doesn't declare its tags.
        raise SmokeError("wheel_no_tags", wheel_path)

    filename_tag_set = {str(t) for t in filename_tags}
    # packaging's Tag str is "<interpreter>-<abi>-<platform>"
    # which is what WHEEL Tag: lines also use.
    undeclared = declared - filename_tag_set
    if undeclared:
        raise SmokeError(
            "wheel_tag_mismatch",
            f"WHEEL declares {sorted(undeclared)}, filename has "
            f"{sorted(filename_tag_set)}",
        )


# ── RECORD ─────────────────────────────────────────────────────

def _parse_record(
    zf: zipfile.ZipFile, dist_info: str,
) -> list[RecordEntry]:
    """Parse RECORD into RecordEntry objects.

    Uses csv.reader because paths can contain commas (rare but
    legal). Hashes are sha256=<urlsafe-base64, no padding>, not
    hex — comparing hexdigests would reject every legitimate
    wheel.
    """
    record_path = f"{dist_info}/RECORD"
    try:
        raw = zf.read(record_path)
    except KeyError as e:
        raise SmokeError("no_record", record_path) from e
    if len(raw) > 10 * 1024 * 1024:
        raise SmokeError("record_too_large", str(len(raw)))

    entries: list[RecordEntry] = []
    reader = csv.reader(
        io.StringIO(raw.decode("utf-8", errors="replace")),
    )
    for i, row in enumerate(reader):
        if i > MAX_RECORD_ENTRIES:
            raise SmokeError(
                "record_too_many_entries", str(MAX_RECORD_ENTRIES),
            )
        if not row:
            continue
        if len(row) != 3:
            raise SmokeError(
                "record_malformed_row",
                f"row {i}: {row!r}",
            )
        path, hash_field, _size = row
        if not hash_field:
            entries.append(RecordEntry(
                path=path, hash_alg="", hash_value="",
            ))
            continue
        if "=" not in hash_field:
            raise SmokeError(
                "record_bad_hash_field",
                f"row {i}: {hash_field!r}",
            )
        alg, b64 = hash_field.split("=", 1)
        alg = alg.strip().lower()
        if alg in ("md5", "sha1"):
            raise SmokeError(
                "record_weak_hash", f"{alg} at row {i}",
            )
        if alg != "sha256":
            raise SmokeError(
                "record_unknown_hash", f"{alg} at row {i}",
            )
        entries.append(RecordEntry(
            path=path, hash_alg=alg, hash_value=b64,
        ))
    return entries


def _verify_record_bidirectional(
    zf: zipfile.ZipFile, entries: list[RecordEntry],
) -> None:
    """
    Bidirectional check:

      Direction 1 — every non-RECORD zip member appears in RECORD.
        Catches an unlisted `.pth` (which runs `import` at every
        interpreter start), an unlisted module, or an unlisted
        data file.

      Direction 2 — every RECORD entry (except RECORD and its
        signature files) hashes correctly. Catches corruption.

    Only RECORD and RECORD.jws/RECORD.p7s may have an empty
    hash. Any other entry with an empty hash would let an
    attacker list a file without a hash and skip verification.
    """
    record_paths = {
        e.path for e in entries if e.path.endswith(("/RECORD", "RECORD"))
    }
    # The RECORD itself and its signature files are exempt from
    # both directions of the check.
    exempt_suffixes = ("/RECORD", "/RECORD.jws", "/RECORD.p7s",
                       "RECORD", "RECORD.jws", "RECORD.p7s")

    def is_exempt(path: str) -> bool:
        return path.endswith(exempt_suffixes)

    # Direction 1: every non-exempt zip member must appear in
    # RECORD.
    recorded = {e.path for e in entries}
    for name in zf.namelist():
        if name.endswith("/"):
            continue  # directory entry
        if is_exempt(name):
            continue
        if name not in recorded:
            raise SmokeError(
                "record_unlisted_file",
                f"{name!r} is in the zip but not in RECORD",
            )

    # Direction 2: every RECORD entry hashes correctly. Skip
    # exempt paths.
    for entry in entries:
        if is_exempt(entry.path):
            continue
        if not entry.hash_alg:
            raise SmokeError(
                "record_empty_hash",
                f"{entry.path!r} has an empty hash",
            )
        try:
            data = zf.read(entry.path)
        except KeyError:
            raise SmokeError(
                "record_missing_file",
                f"{entry.path!r} in RECORD but not in zip",
            )
        if len(data) > MAX_DECOMPRESSED_BYTES:
            raise SmokeError(
                "record_member_too_large",
                f"{entry.path}: {len(data)}",
            )
        actual = hashlib.sha256(data).digest()
        actual_b64 = base64.urlsafe_b64encode(actual).rstrip(b"=").decode()
        if actual_b64 != entry.hash_value:
            raise SmokeError(
                "record_hash_mismatch",
                f"{entry.path!r}",
            )


def _check_pth_files(zf: zipfile.ZipFile) -> None:
    """
    Refuse any `.pth` file whose non-comment lines start with
    `import`. Those execute at every interpreter start — a
    classic supply-chain persistence vector. `.pth` files with
    only paths are legitimate; `.pth` files with `import` are
    not.
    """
    for name in zf.namelist():
        if not name.endswith(".pth"):
            continue
        raw = zf.read(name)
        if len(raw) > 64 * 1024:
            raise SmokeError("pth_too_large", f"{name}: {len(raw)}")
        for line in raw.decode("utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("import "):
                raise SmokeError(
                    "pth_import_line",
                    f"{name}: {stripped!r}",
                )


def _top_level_modules_from_record(
    entries: list[RecordEntry],
) -> list[str]:
    """
    Extract top-level module names from RECORD entries.

    A top-level module is the first path component of an entry
    that ends in .py or is a package's __init__.py. Directories
    like `pkg/__init__.py` yield "pkg"; files like `mod.py` yield
    "mod". Entries under `<name>.dist-info/` are skipped.

    Returns a sorted, deduplicated list. Empty list means the
    wheel declares no importable modules — a strong signal that
    it's not a real wheel.
    """
    modules: set[str] = set()
    for entry in entries:
        path = entry.path
        if ".dist-info/" in path:
            continue
        parts = path.split("/")
        if not parts:
            continue
        first = parts[0]
        if first.endswith(".py"):
            # Top-level single-file module.
            modules.add(first.removesuffix(".py"))
            continue
        # Top-level package: first component is a directory,
        # and somewhere in the wheel there's a first/__init__.py.
        if path.endswith("/__init__.py") and len(parts) >= 2:
            modules.add(first)
    return sorted(modules)


# ── tag compatibility ──────────────────────────────────────────

async def _check_tag_compatibility(filename_info) -> None:
    """The wheel's tag set must intersect the verifier's supported
    tags. Refuses a wheel built for a different Python or platform
    before the container tries to install it."""
    try:
        supported = await get_supported_tags()
    except PreflightError as e:
        raise SmokeError(
            "preflight_failed", f"{e.reason}: {e.detail}",
        ) from e

    _name, _version, _build, wheel_tags = filename_info
    wheel_tag_set = {str(t) for t in wheel_tags}
    if not (wheel_tag_set & supported):
        # Show the intersection attempt for the reader.
        raise SmokeError(
            "unsupported_wheel",
            f"wheel tags {sorted(wheel_tag_set)} do not intersect "
            f"verifier's {len(supported)} supported tags",
        )


# ── container import check ─────────────────────────────────────

async def _check_imports(
    *,
    wheel_host_path: Path,
    top_modules: list[str],
    expected_name: str,
) -> None:
    """
    Install the wheel with --no-index --no-deps --target into a
    tmpfs inside a sandboxed container, then find_spec each
    top-level module.

    find_spec locates the module without executing it. `import
    <module>` would run the module's top-level code, which could
    have side effects — including, for a hostile wheel, code that
    tries to reach the network or the host filesystem. find_spec
    is the inspection without the execution.
    """
    timeout = settings.BUILD_SMOKE_TIMEOUT_SECONDS
    container_name = f"aegis-smoke-{__import__('uuid').uuid4().hex[:12]}"

    module_check = (
        "import importlib.util, sys\n"
        + "".join(
            f"if importlib.util.find_spec({m!r}) is None:\n"
            f"    print('MISSING:' + {m!r}); sys.exit(1)\n"
            for m in top_modules
        )
    )

    script = (
        "set -e\n"
        "pip install --no-index --no-deps "
        "--target /tmp/wheeltest "
        f"{wheel_host_path.name}\n"
        "PYTHONPATH=/tmp/wheeltest python -c "
        + _shell_quote(module_check)
        + "\n"
    )

    argv = [
        "docker", "run", "--rm",
        "--name", container_name,
        "--network", "none",
        "--read-only",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--pids-limit", "32",
        "--tmpfs", "/tmp:rw,size=256m,mode=1777",
        "-v", f"{wheel_host_path}:/wheel/{wheel_host_path.name}:ro",
        "-w", "/wheel",
        settings.VERIFY_DOCKER_IMAGE_PYTHON,
        "sh", "-c", script,
    ]

    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(
            proc.communicate(), timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        try:
            await proc.wait()
        except Exception:
            pass
        try:
            kp = await asyncio.create_subprocess_exec(
                "docker", "kill", container_name,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            await kp.wait()
        except Exception:
            pass
        raise SmokeError(
            "import_timeout", f"{timeout}s",
        )

    output = out.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        # Extract the missing module from our own check if
        # present, else report the tail.
        if "MISSING:" in output:
            missing = output.split("MISSING:")[-1].strip().splitlines()[0]
            raise SmokeError(
                "module_not_importable",
                f"{missing}",
            )
        raise SmokeError(
            "import_failed",
            f"exit={proc.returncode} tail={output[-1000:]!r}",
        )


def _shell_quote(s: str) -> str:
    """Single-quote for sh. Escapes embedded single quotes the
    POSIX way: end quote, escaped quote, resume quote."""
    return "'" + s.replace("'", "'\\''") + "'"
