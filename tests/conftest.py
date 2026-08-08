from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    project_root = Path(__file__).resolve().parents[1]
    home = tmp_path / "study-home"
    return Settings(
        home=home,
        db_path=home / "workbench.db",
        library_dir=home / "library",
        export_dir=home / "exports",
        static_dir=project_root / "app" / "static",
    )


@pytest.fixture()
def client(settings: Settings):
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client
