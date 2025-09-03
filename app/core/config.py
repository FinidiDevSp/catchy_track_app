from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    app_name: str = Field(default="Catchy Track App")
    debug: bool = Field(default=True)
    database_url: str = Field(default="sqlite:///data/app.db")
    allowed_roots: str = Field(default="./sandbox", description="Comma separated list of roots")
    log_level: str = Field(default="INFO")

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
