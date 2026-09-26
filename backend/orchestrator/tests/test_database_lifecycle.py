"""
Integration tests for the database session lifecycle.

These tests hit the real Postgres container (docker-compose), not a mock.
That's the point: the bug in #74 was invisible to mocked tests because
they replaced get_db entirely. The only way to verify the fix is to
exercise a real session against a real connection pool.

Run with:
    docker-compose --env-file ci.env exec orchestrator \
        python -m pytest tests/test_database_lifecycle.py -v

--------------------------------------------------------------------------
Event loop model
--------------------------------------------------------------------------
These tests use the module-level engine from src.database, whose
connection pool holds asyncpg connections for the lifetime of the test
session. asyncpg binds each connection to the loop it was created on, so
the loop must outlive any single test.

pyproject.toml sets:
    asyncio_default_test_loop_scope = "session"
    asyncio_default_fixture_loop_scope = "session"

That guarantees one loop for the whole session, matching the pool's
lifetime. Without it, pytest-asyncio creates a fresh loop per test,
the pool hands a connection created on a closed loop to the next test,
and pool_pre_ping raises 'got Future attached to a different loop'.
"""
import asyncio

import pytest
from sqlalchemy import text

from src.database import engine, get_db, get_db_session


# ---------------------------------------------------------------------------
# The fix, positively verified
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_db_session_yields_open_session():
    """
    A session from get_db_session must remain usable for the duration of
    the caller's block, including multiple statements.
    """
    async with get_db_session() as session:
        r1 = await session.execute(text("SELECT 1 AS one"))
        assert r1.scalar() == 1

        r2 = await session.execute(text("SELECT 2 AS two"))
        assert r2.scalar() == 2


@pytest.mark.asyncio
async def test_get_db_session_rolls_back_on_exception():
    """
    An exception inside the block must not leave a half-open transaction.
    After the block exits, the connection must be back in the pool, clean.
    """
    class IntentionalError(RuntimeError):
        pass

    with pytest.raises(IntentionalError):
        async with get_db_session() as session:
            await session.execute(text("SELECT 1"))
            raise IntentionalError("intentional test failure")

    async with get_db_session() as session:
        r = await session.execute(text("SELECT 3"))
        assert r.scalar() == 3


@pytest.mark.asyncio
async def test_pool_not_exhausted_across_repeated_calls():
    """
    The old get_db() leaked a connection per call. 50 sequential calls
    would exhaust pool_size=10 + max_overflow=20. This test proves the
    new pattern reuses the pool cleanly.

    On the old code, this test would raise TimeoutError around call ~31.
    """
    for i in range(50):
        async with get_db_session() as session:
            r = await session.execute(
                text("SELECT CAST(:n AS int)"), {"n": i}
            )
            assert r.scalar() == i


@pytest.mark.asyncio
async def test_concurrent_sessions_do_not_block():
    """
    The pool must serve concurrent sessions without deadlocking.
    10 concurrent tasks matches pool_size — if the pool is healthy,
    they all complete.
    """
    async def one(n: int) -> int:
        async with get_db_session() as session:
            r = await session.execute(
                text("SELECT CAST(:n AS int)"), {"n": n}
            )
            return r.scalar()

    results = await asyncio.gather(*(one(i) for i in range(10)))
    assert sorted(results) == list(range(10))


# ---------------------------------------------------------------------------
# The deprecation shim, negatively verified
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_db_raises_deprecation_error():
    """
    The old get_db must fail loudly. If a caller is missed during
    migration, this turns a silent connection leak into a loud crash.
    """
    with pytest.raises(RuntimeError, match="#74"):
        await get_db()


# ---------------------------------------------------------------------------
# Pool health after the suite
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_engine_pool_not_saturated():
    """
    After all the above tests, the engine's pool should be back to
    steady state — no checked-out connections leaking.
    """
    pool = engine.pool
    checked_out = pool.checkedout()
    assert checked_out == 0, f"Pool has {checked_out} leaked connections"
