import os
import tempfile

import pytest

_tmp_dir = tempfile.mkdtemp(prefix="billproof-test-")
os.environ["APP_ENV"] = "test"
os.environ["BILLPROOF_DB_DIR"] = _tmp_dir  # isolates tests from data/store/
os.environ["DEMO_MODE"] = "true"

from billproof import store
from billproof.api.main import app


@pytest.fixture(autouse=True)
async def _fresh_db():
    """Every test (API or direct-service) gets an isolated database backed by
    a per-session temp dir. Connecting here rather than relying on FastAPI's
    lifespan means unit tests that call services/repositories directly also
    get a live db, and tests that shell out to scripts/seed.py as a
    subprocess (it inherits BILLPROOF_DB_DIR) see the same data."""
    await store.connect()
    store.reset_state()
    yield
    await store.close()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    # The `with` block eagerly opens TestClient's background event-loop
    # portal (and its real self-pipe socket) at fixture setup, before any
    # test body gets a chance to monkeypatch socket.socket -- otherwise the
    # portal is created lazily on the first request instead. store.connect/
    # close are idempotent, so this app-lifespan call never conflicts with
    # _fresh_db's own connect/close.
    with TestClient(app) as c:
        yield c
