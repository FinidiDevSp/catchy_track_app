# Catchy Track App — Backend (FastAPI)

This repository contains a robust FastAPI backend scaffold with a first endpoint to process folders. It validates input, records folder names into a database, and deletes processed folders safely.

## Features
- FastAPI app with modular structure (`app/`)
- Pydantic Settings via `.env`
- SQLAlchemy (SQLite by default)
- Synchronous processing (endpoint waits for completion)
- Safe path checks against allowed roots
- File locking to prevent concurrent conflicting runs
- Structured logging
- VS Code debug config
- Pre-commit (black, isort, flake8)
- GitHub Actions CI (lint + tests)

## Quickstart
1. Create a virtualenv and install deps:
   - `python -m venv .venv && .\\.venv\\Scripts\\activate` (Windows)
   - `python -m venv .venv && source .venv/bin/activate` (macOS/Linux)
   - `pip install -e .[dev]`
2. Copy `.env.example` to `.env` and adjust if needed.
3. Run the server (VS Code launch config "FastAPI (uvicorn) — debug" or):
   - `uvicorn app.main:app --reload`
4. Open docs at `http://localhost:8000/docs`.

## Endpoint: Process Folders
POST `/api/v1/folders/process`
- Request body:
  - `action`: `ALLOW` | `DENY`
  - `path`: absolute or relative path inside an allowed root
- Behavior:
  - Verifies the folder exists, is a directory, and is inside `ALLOWED_ROOTS` (security)
  - Enumerates immediate subfolders only (not recursive)
  - Saves each subfolder name to DB (table `folder_events`) with fields: `action`, `slug`, `name`
  - Deletes each processed subfolder (safely handles Windows read-only files)
  - Returns counts and details; waits for completion before responding

## Configuration
- `.env` keys:
  - `DEBUG=true|false`
  - `DATABASE_URL=sqlite:///data/app.db` (default)
  - `ALLOWED_ROOTS=./sandbox` (comma-separated list)
  - `LOG_LEVEL=INFO|DEBUG|...`
- On startup the app ensures DB tables exist and creates any missing allowed root directories.

## Development
- Pre-commit: `pre-commit install`
- Format/lint: `black . && isort . && flake8`
- Tests: `pytest -q`

## Security Notes
- Only paths under `ALLOWED_ROOTS` are processed/deleted to avoid destructive operations elsewhere.
- Symlinks are skipped.
- File lock (`.process.lock`) prevents concurrent processing of the same path.
- The endpoint runs synchronously (no background tasks) to guarantee completion before response.

## Conventional Commits
Use Conventional Commits for messages, e.g.:
- `feat(api): add folder processing endpoint`
- `fix(service): handle read-only files on Windows`

## GitHub Actions
CI runs on pushes/PRs to `main`/`master` and executes pre-commit hooks and tests.
