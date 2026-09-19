import os
import tempfile

import pytest

_tmp_dir = tempfile.mkdtemp(prefix="billproof-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_dir}/test.db"
os.environ["APP_ENV"] = "test"
os.environ["DEMO_MODE"] = "true"
os.environ["BILLPROOF_PROVENANCE_LOG"] = f"{_tmp_dir}/provenance.json"

from billproof.api.main import app
from billproof.db import Base, engine, init_db


@pytest.fixture(autouse=True)
def _fresh_db():
    Base.metadata.drop_all(bind=engine)
    init_db()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c
