"""
Build hostile wheels.

These are the outputs a compromised or buggy build container might
produce. The smoke test refuses each with a specific reason.

Each builder constructs a real wheel via zipfile — a valid zip,
a valid .dist-info, a valid METADATA — with one specific
violation. The tests assert the smoke test's reason, not "the
wheel is bad somehow."
"""
from __future__ import annotations

import base64
import hashlib
import io
import zipfile


def _sha256_b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(
        hashlib.sha256(data).digest()
    ).rstrip(b"=").decode()


def _base_wheel_files(
    *,
    name: str = "aegis-hostile",
    version: str = "0.0.1",
    module_dir: str = "aegis_hostile",
) -> dict[str, bytes]:
    """Minimal valid wheel contents (no RECORD yet)."""
    dist_info = f"{name.replace('-', '_')}-{version}.dist-info"
    return {
        f"{module_dir}/__init__.py": b"# module init\n",
        f"{dist_info}/METADATA":
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
            .encode("utf-8"),
        f"{dist_info}/WHEEL":
            b"Wheel-Version: 1.0\nTag: py3-none-any\n",
    }


def _finalize_wheel(
    files: dict[str, bytes],
    *,
    name: str = "aegis-hostile",
    version: str = "0.0.1",
    extra_record_entries: list[str] | None = None,
) -> bytes:
    """Add RECORD and zip everything into a wheel."""
    dist_info = f"{name.replace('-', '_')}-{version}.dist-info"
    record_lines = []
    for path, content in files.items():
        digest = _sha256_b64(content)
        record_lines.append(f"{path},sha256={digest},{len(content)}")
    for extra in (extra_record_entries or []):
        record_lines.append(extra)
    record_lines.append(f"{dist_info}/RECORD,,")
    files = dict(files)
    files[f"{dist_info}/RECORD"] = "\n".join(record_lines).encode("utf-8")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in files.items():
            zf.writestr(path, content)
    return buf.getvalue()


# ── 1. zip bomb ───────────────────────────────────────────────

def zip_bomb_wheel(
    *,
    member_name: str = "aegis_hostile/big.bin",
    decompressed_size: int = 700 * 1024 * 1024,  # 700 MB
) -> bytes:
    """
    A wheel with one member that decompresses to 700MB of zeros.

    Expected: the smoke test's RECORD verifier refuses with
    `record_member_too_large` because the decompressed size of
    the member exceeds MAX_DECOMPRESSED_BYTES per member.

    Note: RECORD will list the member with a hash of 700MB of
    zeros, which is cheap to compute. The zip itself is small.
    """
    files = _base_wheel_files()
    # A valid RECORD entry for the bomb (correct hash of 700MB
    # of zeros). The smoke test's per-member read fails on the
    # size, not on the hash — that's the defense being exercised.
    big_hash = hashlib.sha256()
    chunk = b"\x00" * (1024 * 1024)
    written = 0
    while written < decompressed_size:
        take = min(len(chunk), decompressed_size - written)
        big_hash.update(chunk[:take])
        written += take
    digest = base64.urlsafe_b64encode(
        big_hash.digest()
    ).rstrip(b"=").decode()

    dist_info = "aegis_hostile-0.0.1.dist-info"
    record_lines = []
    for path, content in files.items():
        record_lines.append(
            f"{path},sha256={_sha256_b64(content)},{len(content)}"
        )
    record_lines.append(
        f"{member_name},sha256={digest},{decompressed_size}"
    )
    record_lines.append(f"{dist_info}/RECORD,,")
    files = dict(files)
    files[f"{dist_info}/RECORD"] = "\n".join(record_lines).encode("utf-8")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in files.items():
            zf.writestr(path, content)
        # Write the bomb member. 700MB of zeros compresses to
        # about 700KB, so the wheel is small at the disk level.
        written = 0
        with zf.open(member_name, "w") as member:
            while written < decompressed_size:
                take = min(len(chunk), decompressed_size - written)
                member.write(chunk[:take])
                written += take
    return buf.getvalue()


# ── 2. duplicate member names ─────────────────────────────────

def duplicate_member_wheel() -> bytes:
    """
    A wheel with two zip members that have the same name but
    different contents. Different zip parsers resolve duplicates
    differently — one tool may read the first, another the
    second. That's a confusion vector: a scanner sees one
    content, the installer sees another.

    Expected: the smoke test's RECORD verifier refuses with
    `record_unlisted_file` or `record_hash_mismatch` — the
    RECORD lists one hash for the name, and one of the two
    physical members won't match it (whichever the zipfile
    library returns for `zf.read`).

    Note: the Python `zipfile` module warns on duplicate names
    when writing. The test builds the wheel using a low-level
    approach: write one member, then write a second with the
    same name.
    """
    files = _base_wheel_files()
    dist_info = "aegis_hostile-0.0.1.dist-info"

    # Build the base zip, then reopen in append mode and write a
    # second copy of an existing member with different contents.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in files.items():
            zf.writestr(path, content)
        # A member that will also appear in RECORD, with the
        # first content's hash.
        zf.writestr(
            "aegis_hostile/dup.py",
            b"# first content\n",
        )
        # RECORD lists the first content.
        record_lines = []
        for path, content in files.items():
            record_lines.append(
                f"{path},sha256={_sha256_b64(content)},{len(content)}"
            )
        record_lines.append(
            f"aegis_hostile/dup.py,sha256="
            f"{_sha256_b64(b'# first content')},16"
        )
        record_lines.append(f"{dist_info}/RECORD,,")
        zf.writestr(
            f"{dist_info}/RECORD",
            "\n".join(record_lines).encode("utf-8"),
        )
        # The duplicate. Different contents, same name.
        zf.writestr(
            "aegis_hostile/dup.py",
            f"# DIFFERENT second content — this is the confusion vector\n",
        )
    return buf.getvalue()


# ── 3. unlisted .pth ──────────────────────────────────────────

def unlisted_pth_wheel() -> bytes:
    """
    A wheel with a `.pth` file that runs `import` at interpreter
    start, and that isn't listed in RECORD.

    Expected: the smoke test's RECORD verifier refuses with
    `record_unlisted_file`.

    A `.pth` starting with `import` runs code at every
    interpreter startup. An unlisted one isn't verified by
    RECORD (there's nothing to check its hash against), so it
    can appear silently in a wheel that otherwise looks fine.
    The smoke test catches it by the bidirectional check: every
    zip member must be in RECORD, or the wheel is refused.
    """
    files = _base_wheel_files()
    dist_info = "aegis_hostile-0.0.1.dist-info"

    # A .pth that would run arbitrary code at interpreter start.
    files["aegis_hostile/import_hook.pth"] = (
        b"import os\nos.system('touch /tmp/pwned')\n"
    )

    # Build RECORD *without* the .pth entry.
    record_lines = []
    for path, content in files.items():
        if path.endswith(".pth"):
            continue
        record_lines.append(
            f"{path},sha256={_sha256_b64(content)},{len(content)}"
        )
    record_lines.append(f"{dist_info}/RECORD,,")
    files[dist_info + "/RECORD"] = "\n".join(record_lines).encode("utf-8")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in files.items():
            zf.writestr(path, content)
    return buf.getvalue()
