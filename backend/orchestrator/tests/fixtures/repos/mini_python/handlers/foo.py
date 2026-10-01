"""Fixture for #105 case B — the null source is not visible in the repo.

`result` comes from an external package, and `result.data` is a
property we cannot resolve. The agent should refuse, not guess.
"""


async def handler(request):
    result = await fetch_external(request)
    return result.data.value


async def fetch_external(request):
    raise NotImplementedError("stubbed in fixture")
