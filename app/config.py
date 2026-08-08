from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    home: Path
    db_path: Path
    library_dir: Path
    export_dir: Path
    static_dir: Path
    max_upload_bytes: int = 500 * 1024 * 1024
    parser_version: str = "pymupdf-1"
    schema_version: int = 4
    ai_provider: str = "local"
    ai_base_url: str = ""
    ai_api_key: str = ""
    ai_model: str = ""

    @classmethod
    def from_env(cls, *, project_root: Path | None = None) -> "Settings":
        root = project_root or Path(__file__).resolve().parents[1]
        home = Path(os.getenv("LAW_STUDY_HOME", str(root / "data"))).expanduser().resolve()
        static_dir = root / "app" / "static"
        return cls(
            home=home,
            db_path=home / "workbench.db",
            library_dir=home / "library",
            export_dir=home / "exports",
            static_dir=static_dir,
            max_upload_bytes=int(os.getenv("LAW_STUDY_MAX_UPLOAD_BYTES", 500 * 1024 * 1024)),
            ai_provider=os.getenv("LAW_STUDY_AI_PROVIDER", "local").strip().lower(),
            ai_base_url=os.getenv("LAW_STUDY_AI_BASE_URL", "").strip(),
            ai_api_key=os.getenv("LAW_STUDY_AI_API_KEY", "").strip(),
            ai_model=os.getenv("LAW_STUDY_AI_MODEL", "").strip(),
        )

    def ensure_directories(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        self.library_dir.mkdir(parents=True, exist_ok=True)
        self.export_dir.mkdir(parents=True, exist_ok=True)
