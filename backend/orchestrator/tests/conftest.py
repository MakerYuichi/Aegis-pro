import pytest


@pytest.fixture(autouse=True)
def _reset_settings(monkeypatch):
    """
    Ensure each test gets a fresh Settings object loaded from the current
    environment, and that no cached provider chain leaks between tests.
    """
    import importlib
    from src import config

    # Reload config so Settings() re-reads env vars set by this test
    importlib.reload(config)

    # Clear any cached providers
    from src.llm import factory
    importlib.reload(factory)

    yield
