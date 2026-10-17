# Build image for source-only Python packages.
#
# Derives from the same pinned base as the verifier image, so any
# wheel this produces is tagged for the same Python, the same
# architecture, and the same libc. The `python:3.11-slim` reference
# must resolve to the same digest the verifier's base resolves to.
# See `backend/orchestrator/base.txt` for the digest; both
# Dockerfiles read from it.
#
# Contains exactly one extra layer over the base: the C toolchain.
# No build backends, no pip-installed packages, no compiled
# libraries. Those arrive through the read-only wheelhouse at build
# time, at the version each sdist asks for.
FROM python:3.11-slim@sha256:e41613d42d4891e4930f79523f93f81bbc7632584ec65e36ab055f41a800b41e

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        build-essential \
 && rm -rf /var/lib/apt/lists/*

# The build entrypoint is mounted read-only at run time; nothing
# is baked in beyond the toolchain.
WORKDIR /build
