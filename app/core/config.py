from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field


class Settings(BaseModel):
    app_name: str = Field(default="Catchy Track App")
    debug: bool = Field(default=True)
    database_url: str = Field(default="sqlite:///data/app.db")
    allowed_roots: str = Field(default="./sandbox", description="Comma separated list of roots")
    log_level: str = Field(default="INFO")
    # Security
    api_key: Optional[str] = Field(default="dev-key", description="API key for protected endpoints")
    auth_enabled: bool = Field(default=True, description="Enable API key auth for /api/v1 routes")
    # CORS / Hosts
    cors_origins: str = Field(
        default="*", description="Comma separated list of allowed CORS origins or *"
    )
    allowed_hosts: str = Field(
        default="127.0.0.1,localhost",
        description="Comma separated list of trusted hosts",
    )

    @property
    def base_dir(self) -> Path:
        # repo root: app/core/config.py -> parents[2]
        return Path(__file__).resolve().parents[2]

    @property
    def allowed_root_paths(self) -> List[Path]:
        roots = [r.strip() for r in self.allowed_roots.split(",") if r.strip()]
        if not roots:
            roots = ["./sandbox"]
        paths: List[Path] = []
        for r in roots:
            p = Path(r)
            if not p.is_absolute():
                p = (self.base_dir / p).resolve()
            else:
                p = p.resolve()
            paths.append(p)
        return paths

    @property
    def cors_origin_list(self) -> List[str]:
        raw = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        return ["*"] if not raw or "*" in raw else raw

    @property
    def allowed_hosts_list(self) -> List[str]:
        hosts = [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]
        return hosts or ["127.0.0.1", "localhost"]


def _repo_root() -> Path:
    # repo root: app/core/config.py -> parents[2]
    return Path(__file__).resolve().parents[2]


def _config_path() -> Path:
    return _repo_root() / "config" / "settings.json"


@lru_cache
def get_settings() -> Settings:
    defaults = Settings()
    path = _config_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Config JSON must be an object")
            merged = {**defaults.model_dump(), **data}
            return Settings(**merged)
        except Exception:
            # On any error, fall back to defaults
            return defaults
    return defaults
