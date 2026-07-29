import os
import tempfile
from pathlib import Path

# Must run before any `app.*` import: app.database binds its engine to
# settings.database_url at import time, and app.config.get_settings() is
# process-lifetime cached, so the test DB has to be in place first.
_TEST_DB_DIR = tempfile.mkdtemp(prefix="shortener_test_")
_TEST_DB_PATH = Path(_TEST_DB_DIR) / "test_shortener.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH.as_posix()}"

import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine, init_db


@pytest.fixture(scope="session", autouse=True)
def _init_test_db():
    init_db()
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_tables():
    yield
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


@pytest.fixture()
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c
