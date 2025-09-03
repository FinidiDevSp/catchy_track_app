from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app


def main():
    settings = get_settings()
    root = settings.allowed_root_paths[0]
    test_dir = Path(root) / "testroot"
    (test_dir / "alpha").mkdir(parents=True, exist_ok=True)
    (test_dir / "beta").mkdir(parents=True, exist_ok=True)

    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/folders/process", json={"action": "ALLOW", "path": str(test_dir)}
        )
        print("status", resp.status_code)
        print("json", resp.json())
        print("exists alpha:", (test_dir / "alpha").exists())
        print("exists beta:", (test_dir / "beta").exists())


if __name__ == "__main__":
    main()
