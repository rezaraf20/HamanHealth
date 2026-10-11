"""
Integration tests against a real PostgreSQL (the ingest code uses PostgreSQL-specific
upserts, so SQLite would not test the real thing).

    TEST_DATABASE_URL=postgresql://...  TEST_CLIPS_DATABASE_URL=postgresql://...  pytest

Both databases are wiped and rebuilt with the Alembic migrations, so never point
these at a database you care about.
"""
import os
import subprocess
import sys
import tempfile

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text

MAIN_URL = os.environ.get("TEST_DATABASE_URL")
CLIPS_URL = os.environ.get("TEST_CLIPS_DATABASE_URL")
if not (MAIN_URL and CLIPS_URL):
    pytest.skip("TEST_DATABASE_URL and TEST_CLIPS_DATABASE_URL not set", allow_module_level=True)

_tmp = tempfile.mkdtemp(prefix="haman-test-")
os.environ.update({
    "DATABASE_URL": MAIN_URL,
    "CLIPS_DATABASE_URL": CLIPS_URL,
    "CLIPS_ENCRYPTION_KEY": Fernet.generate_key().decode(),
    "CLIPS_DIR": os.path.join(_tmp, "clips"),
    "RECORDS_DIR": os.path.join(_tmp, "records"),
    "SECRET_KEY": "test-secret",
})

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _reset(url: str, alembic_args: list[str]) -> None:
    eng = create_engine(url)
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    eng.dispose()
    subprocess.run([sys.executable, "-m", "alembic", *alembic_args, "upgrade", "head"],
                   cwd=BACKEND, check=True, env=os.environ.copy(), capture_output=True)


@pytest.fixture(scope="session", autouse=True)
def migrated():
    _reset(MAIN_URL, [])
    _reset(CLIPS_URL, ["-n", "clips"])


@pytest.fixture()
def client(migrated):
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


@pytest.fixture()
def user(client):
    """A fresh registered user; returns auth headers."""
    import uuid
    r = client.post("/api/auth/register",
                    json={"email": f"{uuid.uuid4().hex[:10]}@test.dev", "password": "pw-123456"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access']}"}
