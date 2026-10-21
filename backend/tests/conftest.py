from pathlib import Path

import psycopg
import pytest

from app.config import settings

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def efetch_xml() -> bytes:
    return (FIX / "efetch_sample.xml").read_bytes()


@pytest.fixture
def test_db(monkeypatch):
    """Fresh schema in a throwaway database so tests never touch real data."""
    base = settings.database_url
    admin = base.rsplit("/", 1)[0] + "/postgres"
    name = "longevidence_test"
    try:
        with psycopg.connect(admin, autocommit=True) as c:
            c.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
            c.execute(f"CREATE DATABASE {name}")
    except psycopg.Error as e:
        pytest.skip(f"Postgres unavailable: {e}")
    monkeypatch.setattr(settings, "database_url", base.rsplit("/", 1)[0] + "/" + name)
    from app import db
    db.migrate()
    yield
