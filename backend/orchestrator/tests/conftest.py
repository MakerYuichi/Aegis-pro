import os

# Set dummy Auth0 env vars BEFORE any module imports src.config
# so that src.auth can construct the Auth0FastAPI client without
# real credentials. Tests mock the actual auth behavior.
os.environ.setdefault("AUTH0_DOMAIN", "test-tenant.us.auth0.com")
os.environ.setdefault("AUTH0_AUDIENCE", "https://test-api")
import pytest


@pytest.fixture(autouse=True)
def _reset_settings(monkeypatch):
    """
    Ensure each test gets a fresh Settings object loaded from the current
    environment, and that no cached provider chain or service factory
    leaks between tests.
    """
    import importlib
    from src import config

    # Reload config so Settings() re-reads env vars set by this test
    importlib.reload(config)

    # Reload both factories so their references to `config` and `settings`
    # are fresh
    from src.llm import factory as llm_factory
    importlib.reload(llm_factory)

    from src.services import factory as svc_factory
    importlib.reload(svc_factory)

    yield